@echo off
REM Medical Research Agent - one-time setup for Windows.
REM Double-click this file, or run it in a terminal:  setup.bat

where python >nul 2>nul
if errorlevel 1 (
    echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/
    echo IMPORTANT: tick "Add python.exe to PATH" on the first installer screen.
    pause
    exit /b 1
)

python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements-full.txt

echo.
echo Setup done. Test it with:
echo     python -m tools.pubmed_tool "metformin lactic acidosis"
echo.
echo When you start the agent and RAG parts, run:
echo     pip install -r requirements-full.txt
pause
