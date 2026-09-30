"""LangGraph agent state machine - the Medical Research Agent brain.

Flow: planner -> tool_router (loops over the plan) -> retry (at most once
per failure) -> cross_check -> answer. Every LLM call goes through
agent.llm_client, so the backend (Groq today, Ollama or vLLM later) stays
swappable without touching this file. Tools come from tools.registry, the
single import point - weekend 2 swaps it to MCP without touching this file
either.

Run a question end to end:
    python -m agent.graph "Which adverse events are reported for metformin
    and what does recent literature say?"
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from typing import Callable
from typing import Any, TypedDict

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    raise SystemExit("Missing library. Run:  pip install -r requirements-full.txt")

from agent import llm_client
from tools import registry, cache


class AgentState(TypedDict, total=False):
    """Shared state passed between nodes."""

    question: str
    plan: list[dict[str, str]]  # remaining steps: [{"tool": name, "query": str}]
    tool_results: dict[str, Any]  # "tool(query)" -> result or {"error": ...}
    contradictions: list[str]
    retry_count: int
    failed_steps: list[dict[str, str]]
    answer: str
    sources: list[str]
    last_error: str  # set by tool_router on failure, cleared by retry
    trace: list[str]  # human-readable log of what fired, printed at the end


MAX_RETRIES = 1
EVAL_MODE: ContextVar[bool] = ContextVar("eval_mode", default=False)
EVIDENCE_CAP: ContextVar[int] = ContextVar("evidence_cap", default=3000)
ANSWER_TOKEN: ContextVar[Callable[[str], None] | None] = ContextVar("answer_token", default=None)
MAX_RESULT_CHARS = 3000  # per-tool evidence cap for LLM prompts


def _evidence_summary(tool_results: dict[str, Any]) -> str:
    """Flatten tool results into bounded JSON text for an LLM prompt."""
    parts = []
    for key, result in tool_results.items():
        text = json.dumps(result, indent=1, default=str)
        parts.append(f"### {key}\n{text[:min(MAX_RESULT_CHARS, EVIDENCE_CAP.get())]}")
    return "\n\n".join(parts)


def _collect_sources(tool_results: dict[str, Any]) -> list[str]:
    """Pull citation links out of tool results."""
    sources: list[str] = []
    for result in tool_results.values():
        items = result if isinstance(result, list) else [result]
        for item in items:
            if isinstance(item, dict) and item.get("link"):
                sources.append(item["link"])
    return sources


def planner(state: AgentState) -> dict[str, Any]:
    """Break the user question into an ordered list of tool steps.

    Asks the LLM for a JSON array of {"tool", "query"} steps chosen from the
    registry catalog. Falls back to a sensible default plan if the reply is
    not parseable - the agent should degrade, never crash, on LLM noise.
    """
    catalog = "\n".join(f"- {name}: {desc}" for name, (fn, desc) in registry.TOOLS.items())
    prompt = (
        f"Question: {state['question']}\n\n"
        f"Available tools:\n{catalog}\n\n"
        "Reply with ONLY a JSON array of steps, each an object with keys "
        '"tool" (one of the tool names above) and "query" (the exact search '
        "string for that tool). Pick the 1-4 tools that best answer the "
        "question. For questions about literature, evidence, or studies, "
        "include BOTH search_literature (freshness) and literature_rag (the "
        "local index). No prose, no markdown fences."
    )
    reply = llm_client.complete(prompt, system="You are the planner node of a medical research agent.")

    steps: list[dict[str, str]] = []
    try:
        start, end = reply.index("["), reply.rindex("]") + 1
        for step in json.loads(reply[start:end]):
            if isinstance(step, dict) and step.get("tool") in registry.TOOLS and step.get("query"):
                steps.append({"tool": step["tool"], "query": str(step["query"])})
    except (ValueError, json.JSONDecodeError):
        steps = []

    if not steps:  # fallback: ask everything, let the answer node sort it out
        steps = [{"tool": name, "query": state["question"]} for name in registry.TOOLS]

    return {
        "plan": steps,
        "tool_results": {},
        "contradictions": [],
        "retry_count": 0,
        "failed_steps": [],
        "trace": state.get("trace", [])
        + [f"planner: {len(steps)} step(s) -> " + ", ".join(s['tool'] for s in steps)],
    }


def _run_tool(step: dict[str, str]) -> tuple[Any, bool, str]:
    name, query = step["tool"], step["query"]
    try:
        value, hit = cache.call(name, query, registry.TOOLS[name][0])
        if isinstance(value, dict) and "error" in value:
            return value, hit, str(value["error"])
        return value, hit, ""
    except BaseException as exc:  # Missing env vars may raise SystemExit.
        return {"error": str(exc)}, False, str(exc)


def tool_router(state: AgentState) -> dict[str, Any]:
    """Run independent planned tools concurrently, commit results in plan order."""
    plan = list(state.get("plan", []))
    if not plan:
        return {"trace": state.get("trace", []) + ["tool_router: no steps"]}
    results = dict(state.get("tool_results", {}))
    trace = list(state.get("trace", []))
    failed = []
    with ThreadPoolExecutor(max_workers=min(4, len(plan))) as executor:
        futures = [executor.submit(_run_tool, step) for step in plan]
        for step, future in zip(plan, futures):
            value, cached, error = future.result()
            key = f"{step['tool']}({step['query']})"
            results[key] = value
            if error:
                failed.append(step)
                trace.append(f"tool_router: {key} FAILED ({error})")
            else:
                n = len(value) if isinstance(value, (list, dict)) else 1
                trace.append(f"tool_router: {key} -> {n} result(s)" + (" [cached]" if cached else ""))
    return {"plan": [], "tool_results": results, "trace": trace,
            "failed_steps": failed, "last_error": ""}


def cross_check(state: AgentState) -> dict[str, Any]:
    """Compare evidence across sources and record contradictions.

    Runs only when at least two tools produced real results; otherwise it
    passes through cleanly. LLM failure here degrades to "no check done" -
    a missed check is noted in the trace, never fatal.
    """
    ok = {k: v for k, v in state.get("tool_results", {}).items() if "error" not in str(v)[:20]}
    trace = state.get("trace", [])
    if len(ok) < 2:
        return {"trace": trace + ["cross_check: skipped (<2 sources)"]}

    prompt = (
        f"Question: {state['question']}\n\n"
        f"Evidence from multiple sources:\n{_evidence_summary(ok)}\n\n"
        "Do these sources agree? Reply with ONLY a JSON array of short "
        "contradiction strings, or [] if they are consistent. Focus on "
        "safety-relevant disagreements (e.g. a risk in the literature that "
        "the adverse-event counts or label do not reflect)."
    )
    try:
        reply = llm_client.complete(
            prompt, system="You are the cross-check node of a medical research agent."
        )
        start, end = reply.index("["), reply.rindex("]") + 1
        contradictions = [str(c) for c in json.loads(reply[start:end])]
    except BaseException:
        return {"trace": trace + ["cross_check: LLM check failed, continuing without it"]}

    return {
        "contradictions": contradictions,
        "trace": trace + [f"cross_check: {len(contradictions)} contradiction(s)"],
    }


def retry(state: AgentState) -> dict[str, Any]:
    """Retry each failed tool once, sequentially, without losing other results."""
    results = dict(state.get("tool_results", {}))
    trace = list(state.get("trace", []))
    for step in state.get("failed_steps", []):
        old_key = f"{step['tool']}({step['query']})"
        prompt = (f"This tool call failed: {old_key}\nOriginal question: {state['question']}\n"
                  "Reply with ONLY a shorter search query for the same tool. No prose.")
        try:
            query = llm_client.complete(prompt, system="You reformulate failed tool queries.").strip().splitlines()[0]
            if not query:
                raise ValueError("empty query")
            new_step = {"tool": step["tool"], "query": query}
            value, cached, error = _run_tool(new_step)
            results[f"{step['tool']}({query})"] = value
            if error:
                trace.append(f"retry: {old_key} FAILED again ({error})")
            else:
                trace.append(f"retry: {old_key} -> {query!r}" + (" [cached]" if cached else ""))
        except BaseException as exc:
            trace.append(f"retry: {old_key} unavailable ({exc})")
    return {"tool_results": results, "failed_steps": [], "retry_count": 1, "trace": trace}


def answer(state: AgentState) -> dict[str, Any]:
    """Compose the final answer with inline citations and a confidence note."""
    results = state.get("tool_results", {})
    contradictions = state.get("contradictions", [])
    sources = _collect_sources(results)

    gaps = [k for k, v in results.items() if isinstance(v, dict) and "error" in v]
    prompt = (
        f"Question: {state['question']}\n\n"
        f"Evidence:\n{_evidence_summary(results)}\n\n"
        f"Contradictions found: {contradictions or 'none'}\n"
        f"Sources that failed: {gaps or 'none'}\n\n"
        "Answer the question in 3-6 short paragraphs. Rules:\n"
        "- Every factual claim gets an inline citation like [1], [2] matching "
        "the numbered Sources list you end with (use the links in the evidence).\n"
        "- Mention contradictions and failed sources honestly - do not hide gaps.\n"
        "- End with: Sources (numbered list of links) and one Confidence line "
        "(high/medium/low and why).\n"
        "- This is research information, not medical advice."
    )
    if EVAL_MODE.get():
        prompt += ("\nFor this exam evaluation, write a short clinical rationale comparing the "
                   "leading choices. Then put a separate final line exactly 'Final answer: X' "
                   "where X is A, B, C, or D. Do not call tools or output tool-call syntax.")
    callback = ANSWER_TOKEN.get()
    system = "You are the answer node of a medical research agent."
    final = (llm_client.complete_stream(prompt, system=system, on_token=callback)
             if callback else llm_client.complete(prompt, system=system))

    return {
        "answer": final,
        "sources": sources,
        "trace": state.get("trace", []) + [f"answer: composed ({len(sources)} source link(s))"],
    }


def _route_after_router(state: AgentState) -> str:
    return "retry" if state.get("failed_steps") else "cross_check"


def build_graph() -> Any:
    """Wire the nodes into a compiled LangGraph app."""
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("tool_router", tool_router)
    graph.add_node("cross_check", cross_check)
    graph.add_node("retry", retry)
    graph.add_node("answer", answer)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "tool_router")
    graph.add_conditional_edges(
        "tool_router",
        _route_after_router,
        {"retry": "retry", "cross_check": "cross_check"},
    )
    graph.add_edge("retry", "cross_check")
    graph.add_edge("cross_check", "answer")
    graph.add_edge("answer", END)
    return graph.compile()


app = build_graph()


def run(question: str, on_token: Callable[[str], None] | None = None,
        eval_mode: bool = False, evidence_cap: int = 3000) -> AgentState:
    """Run the graph; an optional callback receives answer text as it arrives."""
    token = ANSWER_TOKEN.set(on_token)
    eval_token = EVAL_MODE.set(eval_mode)
    cap_token = EVIDENCE_CAP.set(evidence_cap)
    try:
        return app.invoke({"question": question, "trace": []})
    finally:
        ANSWER_TOKEN.reset(token)
        EVAL_MODE.reset(eval_token)
        EVIDENCE_CAP.reset(cap_token)


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]) or (
        "Which adverse events are reported for metformin and what does recent literature say?"
    )
    print("Working on the answer...", flush=True)
    final_state = run(question, on_token=lambda part: print(part, end="", flush=True))
    print()

    print("Trace:")
    for line in final_state.get("trace", []):
        print(f"  {line}")
    print("\n" + "=" * 70 + "\n")
    # The answer has already streamed above; do not print a duplicate.
