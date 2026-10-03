# Drug safety evidence workspace

An extension of MedResearch and genomics, not a separate agent framework.
Research prototype only. No clinical advice, validated signal, incidence or causal inference.

## Run on your Mac

Extract this ZIP into Downloads. It creates `medresearch-agent-pv` and leaves previous folders alone.
Stop the old server with Control-C first. Then run:

```bash
cd ~/Downloads/medresearch-agent-pv
bash setup_pv.sh
source .venv/bin/activate
python -m serve.api
```

Open http://localhost:8000/pharmacovigilance. The app may open the regular chat first; use its Drug safety workspace link.

- Snapshot reports need no API key or email. Uncheck live retrieval for a fully local run.
- For live PubMed, open `.env` in VS Code and set `NCBI_EMAIL` to your email. Restart the server after changes. No paid subscription required.
- Regular research chat still uses your existing `GROQ_API_KEY` or local Ollama. Do not paste keys into messages or commit `.env`.
- Explicit chat requests such as `pharmacovigilance metformin` use the same LangGraph registry, router and citation collector, without an LLM call. The full deterministic evidence report is returned to avoid dropping limitations in an LLM rewrite.
- Python 3.10+ required. Dependencies install into this folder's own `.venv`. Installation needs internet. Mac Python 3.13 was not available in the build environment for independent testing.

## What the workflow does

1. Validates an exact stored drug name. No implicit brand-to-generic matching.
2. Queries the actual FAERS SQLite database read-only, using bound parameters. Report counts use distinct report IDs, not reaction rows. Shows top five reactions and receipt-month counts.
3. Retrieves up to five newest openFDA labels, then filters exact generic/brand matches. Inspects boxed warnings, warnings, warnings/cautions, adverse reactions and contraindications. Retains label set ID and effective date.
4. Matches reaction terms lexically, with one explicit diarrhoea/diarrhea spelling alias. Displays matching passages. Separates matched terms from not-found/unavailable evidence, never a definitive labeled/unlabeled classification.
5. Searches PubMed for each of the three highest-count drug-reaction pairs, up to two records each. Shows actual returned titles, dates, abstracts in JSON and PubMed links. Does not assert the paper proves the association.
6. Produces Markdown and full JSON exports containing provenance, missing evidence, source links, limitations and workflow trace. API: POST `/api/pv/report` with `{"drug":"metformin","live":false}`.

## What it deliberately does not do

- No PRR/ROR. The existing corpus is a selected-drug, non-random snapshot; it does not support a representative comparator.
- No full co-reported drug analysis. The previous ingestion discarded medication arrays. Shared IDs among selected query-drug groups are not a substitute.
- No automated clinical signal adjudication, MedDRA ontology mapping, incidence estimates, dose/therapy recommendations or regulatory submissions.
- No automatic live refresh: the bundled snapshot was retrieved September 28, 2026. The existing `python -m tools.fetch_faers` refresh command remains available, but replaces the database and retains its bounded-sampling limits. Live label and PubMed requests are fresh per report. This is an on-demand evidence workflow, not real-time FDA event streaming.

## Data and responsible-use sources

- openFDA adverse events: https://open.fda.gov/apis/drug/event/
- openFDA labels: https://open.fda.gov/apis/drug/label/
- FDA dashboard limitations: https://www.fda.gov/drugs/questions-and-answers-fdas-adverse-event-reporting-system-faers/fda-adverse-event-reporting-system-faers-public-dashboard

The FDA page now calls the dashboard AEMS (formerly FAERS). This package retains the FAERS name for its existing openFDA dataset and endpoint. openFDA warns of quarterly adverse-event updates and possible lag of three months or more. Label retrieval is not a guarantee of the currently distributed or approved formulation's label.

## Test the package

```bash
python -m unittest discover -s tests -v
python -m pharmacovigilance metformin --offline
```

`PV_TEST_EVIDENCE.md` records the measured tests and remaining limits. No GitHub push or deployment was performed.
