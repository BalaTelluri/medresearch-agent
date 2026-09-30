"""Small, private, 24-hour disk cache for public API tool results."""
from __future__ import annotations
import hashlib
import json
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Callable

CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
TTL_SECONDS = 24 * 60 * 60
CACHEABLE = {"search_literature", "query_adverse_events", "get_drug_label", "search_trials"}
_LOCK = Lock()


def call(name: str, query: str, function: Callable[[str], Any]) -> tuple[Any, bool]:
    if os.environ.get("TOOL_CACHE", "on").lower() in ("off", "0", "false") or name not in CACHEABLE:
        return function(query), False
    normalized = " ".join(query.casefold().split())
    digest = hashlib.sha256(json.dumps([name, normalized]).encode()).hexdigest()
    path = CACHE_DIR / f"{digest}.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - saved["at"] < TTL_SECONDS:
            return saved["value"], True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    value = function(query)
    # Cache successful empty results too; do not cache tool-error dicts.
    if isinstance(value, dict) and "error" in value:
        return value, False
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"at": time.time(), "value": value}, ensure_ascii=False)
        tmp = path.with_name(path.name + f".{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except (OSError, TypeError):
        pass  # Read-only deployed filesystem must not break the live tool.
    return value, False
