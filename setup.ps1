# Medical Research Agent - one-time setup for Windows PowerShell.
# Right-click -> Run with PowerShell, or:  .\setup.ps1

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install Python 3.11+ from https://www.python.org/downloads/"
    Write-Host 'IMPORTANT: tick "Add python.exe to PATH" on the first installer screen.'
    exit 1
}

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-full.txt

Write-Host ""
Write-Host "Setup done. Test it with:"
Write-Host '    python -m tools.pubmed_tool "metformin lactic acidosis"'
Write-Host ""
Write-Host "When you start the agent and RAG parts, run:"
Write-Host "    pip install -r requirements-full.txt"
