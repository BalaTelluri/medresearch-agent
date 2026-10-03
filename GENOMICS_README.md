# MedResearch + Genomics

One project, two components: a VCF-to-evidence workflow and a supervised pathogenicity baseline. The existing medical literature agent stays in the same package.

## First run (Mac)

Extract the zip once. Finder creates `medresearch-agent-genomics` in Downloads. Use a separate folder from your previous MedResearch install so you do not overwrite your `.env`.

```sh
cd ~/Downloads/medresearch-agent-genomics
bash setup_genomics.sh
source .venv/bin/activate
python -m serve.api
```

Open http://localhost:8000/genomics. Click "Look up evidence" for the bundled public demo. To enable PubMed, set `NCBI_EMAIL` to your email in this folder's `.env` using VS Code. Copy your existing Groq key into `.env` yourself only if you want the original LLM chat too. Do not paste keys in chat or commit `.env`. Genomic evidence retrieval and prediction do not require an LLM key. The template email is deliberately blank.

The setup installs the lightweight serving stack plus ML dependencies automatically. Python 3.10+ is required. CPU only, no GPU/card/payment. Internet is required for external lookups. The original local RAG embeddings are optional and need the heavier `requirements-full.txt` setup; not bundled with the light install.

## What runs

- Paste GRCh38 `CHROM-POS-REF-ALT` identifiers or load a VCF. Multiallelic records split into separate alleles; max 20 alleles, 200 KB. Only A/C/G/T sequence alleles. Genotype/sample fields are ignored. No liftover or indel normalization: supply left-normalized alleles and the correct reference.
- Exact ClinVar match against a 40,000-variant curated sample; other variants use a remote Tabix query of the full 28 Sep 2026 GRCh38 VCF snapshot. Failure and absence are explicit. Indel representation differences can cause a missing match. This is not a whole-genome annotation pipeline.
- gnomAD v4 (`gnomad_r4`) GraphQL query returns separate exome/genome allele counts, allele numbers and frequencies. Cached responses show retrieval time; delete `genomics/data/gnomad_cache.json` to refresh. gnomAD may be unavailable or contain no match. Neither absence nor rarity determines pathogenicity.
- Existing PubMed tool is reused. ClinVar-linked PubMed IDs are preferred for sampled variants. When there is no linked citation, the gene-level search is clearly labeled and does not prove evidence for the exact allele. Network failures and missing email are shown as unavailable.
- A deterministic evidence summary avoids LLM-invented genetic conclusions. The tool is registered in the existing LangGraph tool registry, with nested citation collection. The original LLM chat can call it for explicit GRCh38 IDs when configured. The standalone genomics workspace does not need an LLM. External LLM invocation itself was not tested without the user's key.
- Classifier scores appear separately from ClinVar. Disagreements and seen-during-training lookups are marked. No personalized therapy selection is implemented.

## Actual test-sample metrics

Full source scan: 4,555,206 VCF records. Eligible: 340,062 benign/likely benign and 100,840 pathogenic/likely pathogenic after filtering. Seed-42 reservoir sample: 20,000 per class, deduplicated Variation IDs, known consequences, single-gene records, germline review statuses with multiple nonconflicting submitters, expert panel or practice guideline.

Fixed random forest: 200 trees, max depth 12, min leaf size 10, class weighting. Features: allele lengths, GC proportions, transition type and molecular consequence. No ClinVar target/review/disease fields, gene identity, record IDs or gnomAD frequency in the classifier. gnomAD is evidence lookup only. No hyperparameter optimization on the test sample.

Train: 31,166 variants / 3,549 genes. Test: 8,834 variants / 888 unseen genes. Zero gene overlap and zero Variation-ID overlap.

| Test-sample measure | Result |
|---|---:|
| Accuracy | 93.14% |
| Balanced accuracy | 92.77% |
| Pathogenic precision | 89.83% |
| Pathogenic recall | 98.26% |
| Pathogenic F1 | 93.86% |
| ROC AUC | 0.9802 |
| Majority-class baseline accuracy | 53.34% |

Confusion matrix, rows true and columns predicted [benign, pathogenic]: `[[3598, 524], [82, 4630]]`. 606 errors, including 524 false pathogenic predictions. The demo intentionally includes a benign allele predicted pathogenic to show the limit honestly. Both demo variants belong to the held-out-gene test sample. A high aggregate score does not make an individual result trustworthy.

These are test-sample metrics, NOT clinical validation. The balanced selected sample is not natural disease prevalence. ClinVar ascertainment and consequence annotations limit generalization. Gene holdout addresses one leakage path but not all biological relatedness. No external cohort, prospective evaluation, functional assays, calibrated probabilities, phenotype or inheritance evaluation. Scores are not patient risks or ACMG classifications. ClinVar remains independent displayed evidence, not replaced by the model.

## Inspect or reproduce

```sh
python -m unittest discover -s tests -v
python -m genomics genomics/demo.vcf --output genomic_report.json
python -m genomics.train
```

The shipped sample, model, metrics, split IDs and all held-out predictions are in `genomics/data/`. Training requires no data download. To rebuild the same sample from the full source (about 189 MB plus 241 MB citations):

```sh
curl -L https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar_20260928.vcf.gz -o clinvar_source.vcf.gz
python -m genomics.build_data clinvar_source.vcf.gz
curl -L https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/var_citations.txt -o clinvar_citations.tsv
python -m genomics.build_citations clinvar_citations.tsv
python -m genomics.train
```

Citation TSV is a live file and may change; the extracted citation mapping shipped with this package is the retrieval used on 1 Oct 2026. The dated VCF link may not be retained forever by NCBI. Sample checksum and provenance are in `manifest.json`. No raw patient data. Model pickle files must only be loaded from a trusted package; do not substitute an untrusted joblib file.

## Privacy and data attribution

Public/demo inputs only. Coordinates go to gnomAD; missing sample matches cause remote ClinVar queries; literature queries go to PubMed. This app has no patient-data security review. Do not upload patient VCFs, identify participants, or use results for diagnosis or treatment.

Original code remains MIT. This tool includes data from ClinVar and gnomAD v4.1 browser API. ClinVar asks for attribution and genetics-professional review before medical use. gnomAD primary data are CC0; no restricted predictor annotations are copied here. PubMed abstracts stay attributed to their sources and are fetched on demand, not bundled as a redistributable full-text corpus.

Sources:
- https://www.ncbi.nlm.nih.gov/clinvar/docs/ftp_primer/
- https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/
- https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/
- https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/var_citations.txt
- https://gnomad.broadinstitute.org/
- https://gnomad.broadinstitute.org/terms

## GitHub

No push was done for you. This is a full-source updated project, not a separate genomics repository. Merge into your own local repository after testing. Do not upload `.env`, `.venv`, or downloaded full datasets. Commit `genomics/`, `tests/test_genomics.py`, `requirements-genomics.txt`, `setup_genomics.sh`, `GENOMICS_README.md`, the README update, and changed `serve/` and `tools/registry.py` and `agent/graph.py`. Model/sample files are deliberately included for reproducibility.
