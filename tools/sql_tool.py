"""Text-to-SQL over a local real openFDA snapshot, with a demo fallback.

The LLM writes one read-only SELECT against the FAERS-like schema, this module
validates it (single statement, SELECT-only, no write keywords) and runs it
against data/faers_real.db if present. When absent, use the explicitly labeled
synthetic data/faers_demo.db. Neither source establishes adverse-event incidence.

Run directly to smoke-test:
    python -m tools.sql_tool "Which reactions are most reported for semaglutide?"
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REAL_DB_PATH = DATA_DIR / "faers_real.db"
DEMO_DB_PATH = DATA_DIR / "faers_demo.db"
MAX_ROWS = 50

SCHEMA = """Table: faers_reports
  primaryid    TEXT     source safety report ID; repeats for each reaction
  drug_name    TEXT     one of: semaglutide, tirzepatide, retatrutide, metformin, empagliflozin, liraglutide
  reaction     TEXT     MedDRA-style reaction term, uppercase (e.g. NAUSEA, PANCREATITIS)
  sex          TEXT     F / M / UNK
  age          INTEGER  patient age in years
  country      TEXT     2-letter country code
  outcome      TEXT     one report-level serious outcome, or Not specified
  report_date  TEXT     ISO received date YYYY-MM-DD
Note: one row per report/reaction. Count DISTINCT primaryid for report counts.
Reports are spontaneous; counts are not incidence or proof of causation.
The agent will state whether the current data is real or synthetic."""

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|attach|detach|pragma|vacuum|replace|create|truncate|grant)\b",
    re.IGNORECASE,
)


def _validate_sql(sql: str) -> str:
    """Accept exactly one read-only SELECT statement, or raise ValueError."""
    cleaned = sql.strip()
    cleaned = re.sub(r"^```(?:sql)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1]
    if ";" in cleaned:
        raise ValueError("Only a single statement is allowed.")
    if not cleaned.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed.")
    if FORBIDDEN.search(cleaned):
        raise ValueError("Read-only database: write statements are not allowed.")
    return cleaned



def data_status() -> dict[str, Any]:
    """Inspect the selected local database instead of assuming it is real."""
    if REAL_DB_PATH.exists():
        try:
            with sqlite3.connect(f"file:{REAL_DB_PATH}?mode=ro", uri=True) as conn:
                conn.execute("SELECT COUNT(*) FROM faers_reports").fetchone()
                provenance = [dict(zip(("drug", "retrieved_at_utc", "api_matching_reports", "sampled_reports", "reaction_rows"), r))
                              for r in conn.execute("SELECT drug_name, retrieved_at_utc, api_matching_reports, sampled_reports, reaction_rows FROM _provenance ORDER BY drug_name")]
            if len(provenance) != 6:
                raise ValueError("Incomplete provenance")
            return {"source": "real", "provenance": provenance,
                    "notice": "Local openFDA FAERS snapshot of actual reports, up to 3,000 per drug; not an exhaustive sample, incidence estimate, or proof of causation."}
        except (sqlite3.DatabaseError, ValueError) as exc:
            raise RuntimeError(f"Real FAERS database is incomplete or corrupt: {exc}") from exc
    return {"source": "demo", "provenance": [],
            "notice": "Local FAERS-like data has 450 SYNTHETIC demo rows, not actual FDA reports. Run python -m tools.fetch_faers to build a real snapshot."}


def query_faers_db(question: str, max_rows: int = MAX_ROWS) -> dict[str, Any]:
    """Answer a natural-language question using the selected FAERS database.

    Returns {"sql": str, "columns": [...], "rows": [...], "row_count": int}.
    Raises ValueError if the generated SQL fails the read-only checks.
    """
    from agent import llm_client

    status = data_status()
    db_path = REAL_DB_PATH if status["source"] == "real" else DEMO_DB_PATH
    if not db_path.exists():
        raise SystemExit("No FAERS database. Run: python -m tools.fetch_faers ")

    prompt = (
        f"{SCHEMA}\n\nActive source: {status['notice']}\n\n"
        "Write ONE SQLite SELECT query answering this question:\n"
        f"{question}\n\n"
        "Count DISTINCT primaryid when counting reports; rows are report-reaction pairs. "
        "Rules: SELECT only, no writes, add LIMIT 50 unless the question asks "
        "for an aggregate. Reply with ONLY the SQL, no prose, no markdown."
    )
    sql = _validate_sql(llm_client.complete(prompt, system="You are a careful SQL generator."))

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
        cursor = conn.execute(sql)
        columns = [d[0] for d in cursor.description or []]
        rows = [list(row) for row in cursor.fetchmany(max_rows)]

    return {"data_source": status["source"], "data_notice": status["notice"],
            "sql": sql, "columns": columns, "rows": rows, "row_count": len(rows),
            "link": "https://open.fda.gov/apis/drug/event/" if status["source"] == "real" else None,
            "provenance": status.get("provenance", [])}


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or "Which reactions are most reported for semaglutide?"
    result = query_faers_db(question)
    print(f"SQL: {result['sql']}\n")
    print(" | ".join(result["columns"]))
    for row in result["rows"][:15]:
        print(" | ".join(str(cell) for cell in row))
    print(f"\n({result['row_count']} row(s) - {result['data_notice']})")
