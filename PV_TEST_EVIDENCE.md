# Measured test evidence, October 2, 2026

## Environment

Linux, CPython 3.10.12. Dependencies installed by `bash setup_pv.sh` into an empty virtual environment. Mac/Python 3.13 installation was not independently tested. No private API key was used.

## Regression and workflow tests

26 tests passed in the development workspace, then 26 in the first ZIP-extracted clean-room installation. A second independent ZIP-extracted clean-room run is recorded below. Tests include the existing 12 genomics tests plus 14 PV/integration tests: measured corpus counts; distinct report-ID counts; monthly counts reconciliation; exact-name rejection; input validation; unchanged database SHA after queries; missing snapshot without synthetic fallback; deliberate PRR and co-medication gaps; lexical label match boundaries/spelling; label-unavailable distinction; offline no-network mode; simulated external failures; report API; no-key full graph/chat API/streaming; existing planner/router/citation path; complete mocked genomics graph regression.

These are correctness/regression tests, not a clinical performance benchmark. Mocked tests are explicitly not proof of external Groq invocation. The original Groq-backed chat invocation was not tested because no key was supplied; the new explicit PV chat route works without it. Genomics lookup/model regression remains passing.

## Live external checks

- Metformin: 3,000 distinct report IDs, 11,502 drug-specific reaction rows. Top counts: nausea 199, diarrhoea 179, blood glucose increased 175, drug ineffective 168, weight decreased 153.
- Live openFDA label retrieval succeeded. Nausea and diarrhoea matched actual retrieved safety passages. The other top terms were not found by lexical check, not established as unlabeled.
- Live PubMed retrieval returned two records for each of the first three pairs. Returned records require human appraisal; they can discuss efficacy or other treatments and are not themselves proof of an adverse effect.
- A complete live no-key LangGraph PV invocation produced the deterministic report and 7 distinct source URLs, without truncating its limits.
- Retatrutide: 44 report IDs; openFDA returned no labels. The report visibly retained that evidence gap rather than declaring its reactions unlabeled.
- Snapshot corpus independently counted: 14,914 distinct report IDs; 69,066 reaction rows. Counts are not unique patients or exhaustive reporting.

## Visual checks

Inspected actual desktop and 390px mobile screenshots with an offline completed report. No mobile horizontal overflow was observed. Also inspected the live metformin report with an expanded source passage. Charts, warnings, titles, counts, link wrapping and exports were readable. Playwright exercised report loading and the Markdown download, which returned `safety-evidence-metformin.md`. The previous MedResearch UI remains intact with a new navigation link.

## Material limits

The snapshot selection is the first bounded matched API reports, not a random sample. Metformin's stored receipt months span October 2013-May 2014 despite retrieval in September 2026. This is an especially clear reason not to market the snapshot as current safety surveillance. The UI and exports expose the receipt timeline and selection method. Live label/PubMed evidence is on-demand; FAERS itself is not streaming. No full co-drug list or representative PRR comparator exists in the inherited snapshot. No claims of confirmed signals, causality, incidence, treatment advice or clinical validation are made.

## Second clean-room verification

Second independent ZIP extraction and fresh environment: 26/26 tests passed. Offline CLI and local HTTP report endpoint returned the measured 3,000-report metformin count. All packaged Python files compiled. Installation artifacts, `.env`, caches and private keys are excluded from the ZIP. The final archive was integrity-tested after adding this evidence file.
