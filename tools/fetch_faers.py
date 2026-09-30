"""Build an auditable local snapshot of actual openFDA FAERS reports.

Run: python -m tools.fetch_faers

This is a bounded sample, not the complete FAERS database. Up to 3,000
matched reports per drug are read with the API's search_after cursor; if fewer
exist, all matches are read. Each report/reaction pair becomes one row. The
source record's safetyreportid and version remain in the table for audit.
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "faers_real.db"
ENDPOINT = "https://api.fda.gov/drug/event.json"
DRUGS = ("semaglutide", "tirzepatide", "retatrutide", "metformin", "empagliflozin", "liraglutide")
MAX_REPORTS_PER_DRUG = 3000
PAGE_SIZE = 500


def _date(value: str) -> str | None:
    value = str(value or "")
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}" if len(value) == 8 and value.isdigit() else None


def _age_years(patient: dict) -> int | None:
    try:
        age = float(patient["patientonsetage"])
        unit = str(patient.get("patientonsetageunit", ""))
        years = {"801": age, "802": age / 12, "803": age / 52.1775, "804": age / 365.25}.get(unit)
        return int(round(years)) if years is not None and 0 <= years <= 120 else None
    except (TypeError, ValueError, KeyError):
        return None


def _outcome(report: dict) -> str:
    # These are REPORT-level serious-outcome fields, not reaction causality.
    fields = (("seriousnessdeath", "Death"), ("seriousnesslifethreatening", "Life-Threatening"),
              ("seriousnesshospitalization", "Hospitalization"),
              ("seriousnessdisabling", "Disability"),
              ("seriousnessother", "Other Serious"))
    return next((label for key, label in fields if str(report.get(key)) == "1"), "Not specified")


def _rows(report: dict, drug: str):
    patient = report.get("patient") or {}
    if not isinstance(patient, dict):
        return
    report_id = str(report.get("safetyreportid", "")).strip()
    if not report_id:
        return
    sex = {"1": "M", "2": "F"}.get(str(patient.get("patientsex", "")), "UNK")
    country = str(report.get("primarysourcecountry") or report.get("occurcountry") or "")[:2]
    report_date = _date(report.get("receivedate"))
    version = str(report.get("safetyreportversion", ""))
    reactions = patient.get("reaction") or []
    seen = set()
    for item in reactions:
        if not isinstance(item, dict):
            continue
        reaction = str(item.get("reactionmeddrapt") or "").strip().upper()
        if not reaction or reaction in seen:
            continue
        seen.add(reaction)
        yield (report_id, version, drug, reaction, sex, _age_years(patient), country,
               _outcome(report), report_date)


def _next_url(header: str) -> str | None:
    for part in header.split(","):
        if 'rel="next"' in part.lower():
            candidate = part.split("<", 1)[-1].split(">", 1)[0]
            parsed = urlparse(candidate)
            if parsed.scheme == "https" and parsed.netloc == "api.fda.gov" and parsed.path == "/drug/event.json" and "search_after" in parse_qs(parsed.query):
                return candidate
    return None


def build(db_path: Path = DB_PATH, max_reports: int = MAX_REPORTS_PER_DRUG) -> dict[str, tuple[int, int]]:
    """Fetch reports and atomically replace the database only after every drug succeeds."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = db_path.with_suffix(".db.tmp")
    temporary.unlink(missing_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "MedResearchAgent/1.0 (research demo; openFDA public API)"})
    api_key = os.getenv("OPENFDA_API_KEY", "").strip()
    counts = {}
    try:
        with sqlite3.connect(temporary) as conn:
            conn.execute("""CREATE TABLE faers_reports (
                primaryid TEXT NOT NULL, report_version TEXT, drug_name TEXT NOT NULL,
                reaction TEXT NOT NULL, sex TEXT, age INTEGER, country TEXT,
                outcome TEXT, report_date TEXT,
                PRIMARY KEY (drug_name, primaryid, reaction))""")
            conn.execute("""CREATE TABLE _provenance (
                drug_name TEXT PRIMARY KEY, source_url TEXT NOT NULL, retrieved_at_utc TEXT NOT NULL,
                source_last_updated TEXT, api_matching_reports INTEGER NOT NULL,
                sampled_reports INTEGER NOT NULL, reaction_rows INTEGER NOT NULL,
                max_reports_requested INTEGER NOT NULL, selection TEXT NOT NULL)""")
            for drug in DRUGS:
                query = f'patient.drug.medicinalproduct:"{drug}"'
                params = {"search": query, "limit": min(PAGE_SIZE, max_reports)}
                if api_key:
                    params["api_key"] = api_key
                url = ENDPOINT
                collected, total, updated = 0, None, None
                seen_ids = set()
                while collected < max_reports:
                    for attempt in range(5):
                        response = session.get(url, params=params, timeout=90)
                        if response.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                            time.sleep(min(2 ** attempt, 8))
                            continue
                        response.raise_for_status()
                        break
                    payload = response.json()
                    meta = payload.get("meta", {})
                    total = int(meta.get("results", {}).get("total", 0))
                    updated = meta.get("last_updated")
                    results = payload.get("results") or []
                    if not results:
                        raise RuntimeError(f"Empty page before advertised total for {drug}")
                    for report in results[:max_reports - collected]:
                        report_id = str(report.get("safetyreportid", ""))
                        if report_id in seen_ids:
                            continue
                        seen_ids.add(report_id)
                        conn.executemany("""INSERT OR IGNORE INTO faers_reports
                            (primaryid, report_version, drug_name, reaction, sex, age, country, outcome, report_date)
                            VALUES (?,?,?,?,?,?,?,?,?)""", list(_rows(report, drug)))
                    collected = len(seen_ids)
                    if collected >= min(total, max_reports):
                        break
                    next_url = _next_url(response.headers.get("Link", ""))
                    if not next_url:
                        raise RuntimeError(f"Paging ended early for {drug}: {collected}/{min(total,max_reports)}")
                    url, params = next_url, None
                    time.sleep(0.35)
                row_count = conn.execute("SELECT COUNT(*) FROM faers_reports WHERE drug_name=?", (drug,)).fetchone()[0]
                if not row_count:
                    raise RuntimeError(f"No reaction rows for {drug}; refusing to replace old database")
                conn.execute("INSERT INTO _provenance VALUES (?,?,?,?,?,?,?,?,?)", (
                    drug, ENDPOINT + "?search=" + requests.utils.quote(query, safe=""),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"), updated,
                    total, collected, row_count, max_reports,
                    "openFDA search_after API order; first N matched safety reports, not a random sample or exhaustive dataset"))
                conn.commit()
                counts[drug] = (collected, row_count)
                print(f"{drug}: {collected}/{total} actual reports, {row_count} report-reaction rows", flush=True)
            conn.execute("CREATE INDEX faers_drug_reaction ON faers_reports(drug_name, reaction)")
            conn.execute("CREATE INDEX faers_date ON faers_reports(report_date)")
            conn.commit()
        temporary.replace(db_path)
    finally:
        temporary.unlink(missing_ok=True)
        session.close()
    return counts


if __name__ == "__main__":
    print("Fetching real openFDA FAERS reports (bounded snapshot, not incidence rates)...", flush=True)
    build()
    print(f"Saved {DB_PATH}")
