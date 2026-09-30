"""FastAPI backend serving the Medical Research Agent.

Job-market rationale: REST/APIs appear in ~21% of the tracked German AI/ML
postings and model-deployment skills in ~29% - this module is the piece of
the project that demonstrates both. The browser chat UI is served as a
static page; the agent itself runs in-process via agent.graph.

Run locally (venv active):
    python -m serve.api            # opens http://localhost:8000 automatically
Or with Docker:
    docker build -t medresearch-agent . && docker run -p 8000:8000 --env-file .env medresearch-agent
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

import re
import json
import os
import time
import webbrowser
from queue import Queue
from threading import Thread
from pathlib import Path
from typing import Any

try:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError:
    raise SystemExit("Missing libraries. Run:  pip install -r requirements-full.txt")

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Medical Research Agent", version="1.0.0")

_graph = None


def _get_graph() -> Any:
    """Build the LangGraph app once, lazily (first request compiles it)."""
    global _graph
    if _graph is None:
        from agent.graph import build_graph

        _graph = build_graph()
    return _graph


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    trace: list[str]
    contradictions: list[str]
    sources: list[str]
    confidence: str | None
    tools_used: list[str]


def _confidence(answer: str) -> str | None:
    match = re.search(r"confidence[:\s]*\**(\w+)", answer, re.IGNORECASE)
    return match.group(1).capitalize() if match else None


@app.get("/api/data-status")
def data_status() -> dict:
    """Describe the active local SQL data source for the browser disclaimer."""
    from tools.sql_tool import data_status as inspect_data
    return inspect_data()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    """Run the full agent for one question and return the rendered state."""
    question = req.question.strip()
    if not question:
        return AskResponse(answer="Please ask a question.", trace=[],
                           contradictions=[], sources=[], confidence=None, tools_used=[])
    if len(question) > 1000:
        return AskResponse(answer="Please keep the question under 1,000 characters.", trace=[],
                           contradictions=[], sources=[], confidence=None, tools_used=[])
    state = _get_graph().invoke({"question": question, "trace": []})
    tools_used = sorted({
        line.split("(", 1)[0].replace("tool_router: ", "")
        for line in state.get("trace", [])
        if line.startswith("tool_router:") and "FAILED" not in line
    })
    return AskResponse(
        answer=state.get("answer", "(no answer)"),
        trace=state.get("trace", []),
        contradictions=state.get("contradictions", []),
        sources=state.get("sources", []),
        confidence=_confidence(state.get("answer", "")),
        tools_used=tools_used,
    )


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """NDJSON: token events followed by one complete result event."""
    question = req.question.strip()
    if not question or len(question) > 1000:
        def invalid():
            yield json.dumps({"type": "error", "message": "Question must be 1-1,000 characters."}) + "\n"
        return StreamingResponse(invalid(), media_type="application/x-ndjson")

    def events():
        queue: Queue = Queue()
        def worker():
            try:
                # run() keeps the token callback scoped to this request thread.
                from agent.graph import run
                state = run(question, on_token=lambda text: queue.put({"type": "token", "text": text}))
                tools = sorted({line.split("(", 1)[0].replace("tool_router: ", "")
                    for line in state.get("trace", []) if line.startswith("tool_router:") and "FAILED" not in line})
                queue.put({"type": "done", "answer": state.get("answer", ""),
                    "trace": state.get("trace", []), "contradictions": state.get("contradictions", []),
                    "sources": state.get("sources", []),
                    "confidence": _confidence(state.get("answer", "")), "tools_used": tools})
            except Exception as exc:
                details = str(exc).lower()
                if "groq_api_key" in details and "not set" in details:
                    message = "GROQ_API_KEY is missing. Add your key to .env, then restart the server."
                elif "authenticationerror" in type(exc).__name__.lower() or "invalid api key" in details or "invalid_api_key" in details:
                    message = "The Groq API key was rejected. Check GROQ_API_KEY in .env and restart the server."
                else:
                    message = f"Answer failed: {type(exc).__name__}: {exc}"[:250]
                queue.put({"type": "error", "message": message})
            finally:
                queue.put(None)
        Thread(target=worker, daemon=True).start()
        while True:
            event = queue.get()
            if event is None:
                break
            yield json.dumps(event, ensure_ascii=False) + "\n"
    return StreamingResponse(events(), media_type="application/x-ndjson")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _open_local_browser(server: uvicorn.Server) -> None:
    """Open only after this server has started, not a different process on port 8000."""
    while not server.started and not server.should_exit:
        time.sleep(0.1)
    if server.started and not server.should_exit:
        webbrowser.open("http://localhost:8000/")


if __name__ == "__main__":
    # Hosted/Docker deployments use uvicorn serve.api:app, so never open a browser there.
    # Set AUTO_OPEN_BROWSER=off for a local headless run.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000))
    if os.environ.get("AUTO_OPEN_BROWSER", "on").lower() not in ("off", "false", "0"):
        Thread(target=_open_local_browser, args=(server,), daemon=True).start()
    server.run()
