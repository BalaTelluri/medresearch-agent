#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Install Python 3.10+ from python.org'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
[ -d .venv ] || python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-genomics.txt
[ -f .env ] || cp .env.example .env
echo 'Ready. Run: source .venv/bin/activate; python -m serve.api'
echo 'Open http://localhost:8000/genomics. No API key needed for genomic lookup/model.'
echo 'Set NCBI_EMAIL in .env for PubMed. Existing medical LLM chat uses your existing GROQ_API_KEY.'
