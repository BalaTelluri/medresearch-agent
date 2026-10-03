# Verification on 1 Oct 2026

- Fresh folder and Python 3.10 virtual environment created by `bash setup_genomics.sh`; all pinned serving/ML dependencies installed successfully.
- 12 automated tests passed on the build environment and twice on the clean install: IDs, VCF/multiallelic parsing, deduplication, invalid inputs, assembly mismatch, count/size limits, feature leakage invariance, sample checksum, split integrity, explicit no-therapy output, API endpoints, nested citations.
- Clean-install CLI ran the two public demo variants end to end. ClinVar matched both; gnomAD gave one actual frequency response and one explicit not-found response. PubMed returned three articles each, one gene-level fallback and one ClinVar-linked query. A missing-email run correctly showed literature as unavailable rather than crashing.
- An allele outside the packaged sample (`1-66926-AG-A`) matched the full remote ClinVar snapshot, with uncertain significance / single submitter. It is outside classifier review scope and abstains. Remote queries depend on network and source availability.
- All metrics were independently recomputed from the 8,834 exported predictions, matching exactly. Clean-install retraining reproduced stored metrics exactly. No test-sample tuning.
- Live local API and desktop/mobile Chromium UI tested. Desktop result showed six literature entries, allele frequencies, separate experimental classifier and the explicit ClinVar/model disagreement. No browser JavaScript errors or mobile horizontal overflow. Actual screenshots inspected for layout, readability and result content.
- Current ClinVar web records 52788 and 41543 were opened and agreed with the displayed classifications/coordinates.

Limits: Linux clean-room test, not a physical Mac test. Mac Python wheels are provided by these dependencies but were not installed on the user's Mac. Docker deployment and original Groq-backed chat were not executed; no user's secret was used. Native local serving / genomic workflow / CLI and retraining were executed. Docker files have been updated for the genomics import.
