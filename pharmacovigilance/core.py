"""Deterministic FAERS evidence report. All database access is read-only.

No incidence, causality, drug-response or validated signal claims.
"""
from __future__ import annotations
import config
import re
import sqlite3
import time
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlencode
from tools import openfda_tool, pubmed_tool

ROOT = Path(__file__).resolve().parent.parent
LIMITS = [
    'Exploratory research prototype. Not clinical advice, a validated safety signal, or a regulatory submission.',
    'Counts describe reports in a bounded, drug-enriched, non-random snapshot. They are not patients, incidence, risk or causality.',
    'One report can contain several reactions and drugs. Report ID deduplication does not remove all underlying duplicate cases or reporting bias.',
    'Dates are the stored report receipt dates, not event onset. Changes over time cannot establish changing risk.',
    'No PRR/ROR is calculated: this selected-drug snapshot has no representative all-other-drug comparator.',
    'The original snapshot does not retain full co-reported medication lists. Shared report IDs across selected drugs are not a complete co-medication analysis.',
    'Label matching is lexical in retrieved safety sections only. A missing match does not establish an unlabeled reaction. A match does not validate an association.',
    'PubMed results are retrieved records, not a systematic review or evidence of causality. External text is untrusted evidence, never instructions.',
]

def validate_drug(drug: str) -> str:
    drug = ' '.join(drug.strip().lower().split())
    if not re.fullmatch(r'[a-z][a-z0-9 -]{1,79}', drug):
        raise ValueError('Enter one drug name (2-80 letters, numbers, spaces or hyphens), not a question or patient data.')
    return drug


def snapshot(drug: str, db_path: Path | None = None, top_n: int = 5) -> dict:
    drug = validate_drug(drug)
    path = Path(db_path or ROOT / 'data/faers_real.db').resolve()
    if not path.exists():
        return {'drug': drug, 'error': 'Real FAERS snapshot missing. No synthetic fallback is used for PV.'}
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as con:
        con.row_factory = sqlite3.Row
        available = [r[0] for r in con.execute('SELECT DISTINCT drug_name FROM faers_reports ORDER BY drug_name')]
        # Exact stored query name only. No substring guessing or brand-to-generic inference.
        prov = con.execute('SELECT * FROM _provenance WHERE drug_name=?', (drug,)).fetchone()
        if not prov:
            return {'drug': drug, 'error': 'Drug is not in this snapshot. Use an exact available name.', 'available_drugs': available}
        count = con.execute('SELECT count(DISTINCT primaryid) FROM faers_reports WHERE drug_name=?', (drug,)).fetchone()[0]
        reactions = [dict(r) for r in con.execute('''SELECT reaction, count(DISTINCT primaryid) AS report_count
             FROM faers_reports WHERE drug_name=? GROUP BY reaction ORDER BY report_count DESC, reaction LIMIT ?''', (drug, top_n))]
        # Deduplicate report IDs for dates, keeping the latest stored date if inconsistent.
        months = [dict(r) for r in con.execute('''SELECT substr(d,1,7) AS month, count(*) AS report_count FROM
            (SELECT primaryid, max(report_date) AS d FROM faers_reports WHERE drug_name=? GROUP BY primaryid)
            WHERE d GLOB '????-??-??' GROUP BY month ORDER BY month''', (drug,))]
        missing = con.execute('''SELECT count(*) FROM (SELECT primaryid,max(report_date) AS d FROM faers_reports
            WHERE drug_name=? GROUP BY primaryid) WHERE d IS NULL OR d NOT GLOB '????-??-??' ''', (drug,)).fetchone()[0]
        totals = con.execute('SELECT count(*),count(DISTINCT primaryid) FROM faers_reports').fetchone()
    return {'drug': drug, 'report_count': count, 'reaction_rows': prov['reaction_rows'],
            'corpus_report_count': totals[1], 'corpus_reaction_rows': totals[0],
            'top_reactions': reactions, 'monthly_counts': months, 'missing_date_reports': missing,
            'available_drugs': available, 'provenance': dict(prov), 'source_url': prov['source_url'],
            'co_reported_drugs': {'status': 'unavailable', 'reason': LIMITS[5]},
            'disproportionality': {'status': 'not_computed', 'reason': LIMITS[4]}}


def retrieve_labels(drug: str) -> dict:
    # Reuse the project's openFDA client and optional-key mechanics.
    query = f'openfda.generic_name:"{drug}" OR openfda.brand_name:"{drug}"'
    public_params = {'search': query, 'limit': 5, 'sort': 'effective_time:desc'}
    url = openfda_tool.BASE_URL + '/label.json?' + urlencode(public_params)
    response = openfda_tool.requests.get(openfda_tool.BASE_URL + '/label.json',
        params=openfda_tool._params(dict(public_params)), timeout=20)
    if response.status_code == 404:
        return {'status': 'no_labels_found', 'labels': [], 'source_url': url}
    response.raise_for_status()
    labels = []
    for item in response.json().get('results', []):
        names = item.get('openfda', {})
        # Search can return token matches. Retain only exact generic or brand matches.
        if drug not in [n.lower() for n in names.get('generic_name', []) + names.get('brand_name', [])]:
            continue
        labels.append({'set_id': item.get('set_id'), 'effective_time': item.get('effective_time'),
            'brand_names': names.get('brand_name', []), 'generic_names': names.get('generic_name', []),
            'sections': {k: '\n'.join(item.get(k, [])) for k in ('boxed_warning', 'warnings',
                'warnings_and_cautions', 'adverse_reactions', 'contraindications') if item.get(k)},
            'source_url': url})
    return {'status': 'retrieved' if labels else 'no_exact_labels_found', 'labels': labels,
            'total_api_matches': response.json().get('meta', {}).get('results', {}).get('total'),
            'scope': 'Up to 5 newest returned labels, exact drug-name filter; not all formulations or historical labels.',
            'source_url': url}


def label_check(reaction: str, bundle: dict) -> dict:
    if bundle.get('status') != 'retrieved':
        return {'status': 'unavailable', 'matches': [], 'note': 'Label source unavailable or no exact labels found.'}
    aliases = {reaction.lower(), reaction.lower().replace('diarrhoea', 'diarrhea')}
    matches = []
    for label in bundle['labels']:
        for section, text in label['sections'].items():
            for term in sorted(aliases):
                match = re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text, re.I)
                if match:
                    matches.append({'set_id': label['set_id'], 'effective_time': label.get('effective_time'), 'section': section,
                        'excerpt': text[max(0, match.start()-90):match.end()+120], 'source_url': label['source_url']})
                    break
    return {'status': 'mentioned_in_retrieved_safety_sections' if matches else 'not_found_by_lexical_check',
        'matches': matches, 'note': 'Not a clinical labeled/unlabeled decision. Synonyms, subtypes and other labels may change the result.'}


def build_report(drug: str, live: bool = True, db_path: Path | None = None, top_n: int = 5,
                 literature_n: int = 3) -> dict:
    data = snapshot(drug, db_path, top_n)
    if 'error' in data:
        return data
    trace = ['Validated exact snapshot drug name', 'Read-only SQLite report-ID counts and receipt-month aggregation']
    bundle = {'status': 'not_requested', 'labels': []}
    gaps = []
    if live:
        try:
            bundle = retrieve_labels(data['drug'])
            trace.append('Retrieved openFDA label safety sections; exact drug-name filter')
        except Exception as exc:
            bundle = {'status': 'unavailable', 'labels': [], 'error': type(exc).__name__}
            gaps.append('FDA label lookup failed: ' + type(exc).__name__)
    else:
        gaps.append('Live label and literature retrieval disabled; snapshot-only report.')
    if bundle['status'] != 'retrieved':
        gaps.append('No usable label safety evidence: ' + bundle['status'])
    for i, row in enumerate(data['top_reactions']):
        row['label_check'] = label_check(row['reaction'], bundle)
        row['literature'] = {'status': 'not_requested', 'papers': []}
        if live and i < literature_n:
            query = f'"{data["drug"]}" AND "{row["reaction"].lower()}"'
            try:
                papers = [p.to_dict() for p in pubmed_tool.search_pubmed(query, 2)]
                row['literature'] = {'status': 'retrieved' if papers else 'no_results', 'query': query, 'papers': papers}
            except Exception as exc:
                row['literature'] = {'status': 'unavailable', 'query': query, 'papers': [], 'error': type(exc).__name__}
                gaps.append('PubMed unavailable for ' + row['reaction'] + ': ' + type(exc).__name__)
            time.sleep(0.7)  # public NCBI pacing, also after empty/failed searches
    trace.append('Lexical label comparison; PubMed retrieval for up to three highest-count reactions')
    data.update({'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'label_evidence': bundle,
        'gaps': gaps, 'limitations': LIMITS, 'trace': trace,
        'confidence': 'High for reproducible snapshot counts; limited for label term matching; no causal inference.',
        'framing': 'Exploratory research prototype'})
    data['report_markdown'] = render_report(data)
    return data


def render_report(data: dict) -> str:
    p = data['provenance']
    lines = [f"# Drug safety evidence: {data['drug']}", 'Exploratory research prototype. No clinical, causality or therapy conclusions.',
        f"\n## Snapshot findings\n{data['report_count']:,} distinct report IDs; {data['reaction_rows']:,} reaction rows for this drug.",
        f"Snapshot retrieved {p['retrieved_at_utc']}; upstream last updated {p['source_last_updated']}. Selection: {p['selection']}.",
        f"Source: {data['source_url']}", '\n## Label-mentioned reactions (lexical evidence only)']
    for matched in (True, False):
        if not matched:
            lines.append('\n## Not lexically matched / label evidence unavailable (NOT confirmed unlabeled)')
        rows = [r for r in data['top_reactions'] if (r['label_check']['status'] == 'mentioned_in_retrieved_safety_sections') == matched]
        if not rows:
            lines.append('None in the inspected top reactions.')
        for r in rows:
            lines.append(f"\n### {r['reaction']}: {r['report_count']:,} report IDs\nLabel check: {r['label_check']['status']}.")
            for m in r['label_check']['matches'][:2]:
                lines.append(f"Label set {m['set_id']}, effective {m['effective_time']}, {m['section']}: \"{m['excerpt']}\"\nSource: {m['source_url']}")
            lit = r['literature']
            lines.append('PubMed: ' + lit['status'] + '. Retrieved records only, not a verified causal assessment.')
            for paper in lit['papers']:
                lines.append(f"- {paper['title']} ({paper['pub_date']}) {paper['link']}")
    lines.extend(['\n## Receipt-date pattern', f"{len(data['monthly_counts'])} receipt months represented; {data['missing_date_reports']} reports with missing/invalid dates.",
        'No trend significance or changing risk is inferred.',
        '| Receipt month | Distinct report IDs |', '| --- | ---: |',
        *[f"| {m['month']} | {m['report_count']} |" for m in data['monthly_counts']],
        '\n## Missing evidence', *['- '+g for g in data['gaps']], LIMITS[5], LIMITS[4],
        '\n## Limits', *['- '+x for x in LIMITS], '\nConfidence: '+data['confidence']])
    return '\n'.join(lines)
