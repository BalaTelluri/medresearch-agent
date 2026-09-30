"""Project configuration.

Loads .env once, at import time, from the project root - so every tool works
the same whether the caller remembered to export variables or not. Every
module in this project imports this first:

    import config  # noqa: F401  (loads .env)
"""

from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    raise SystemExit("Missing library. Run:  pip install python-dotenv")

load_dotenv(Path(__file__).resolve().parent / ".env")
