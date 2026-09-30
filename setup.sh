#!/usr/bin/env bash
# Mac/Linux clean setup. Run from the project folder: bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    echo "Python 3.11 or newer is required; found $(python3 --version). Install a current Python from https://www.python.org/downloads/" >&2
    exit 1
fi
if [ ! -d .venv ]; then
    echo "[1/3] Creating Python virtual environment..."
    python3 -m venv .venv
else
    if ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
        echo "Existing .venv has an old Python. Delete .venv and run bash setup.sh again." >&2
        exit 1
    fi
    echo "[1/3] Reusing Python virtual environment..."
fi
echo "[2/3] Updating pip..."
.venv/bin/python -m pip install --upgrade pip
echo "[3/3] Installing project dependencies (large first download; this can take several minutes)..."
.venv/bin/python -m pip install -r requirements-full.txt
echo "Setup complete. Activate with: source .venv/bin/activate"
echo "Set GROQ_API_KEY in .env, then run: python -m serve.api"
echo "Optional: set NCBI_EMAIL in .env to enable PubMed searches."
