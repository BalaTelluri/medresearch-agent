"""Tool registry: the one import point for everything the agent can call.

Weekend 1 wraps the three working tool modules directly. Weekend 2 swaps
each function body for an MCP client call - when that happens, this file
is the only one that changes.
"""

from __future__ import annotations

from typing import Any, Callable

from tools import openfda_tool, pubmed_tool, trials_tool


def search_literature(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search PubMed for papers matching a free-text query (plain dicts out)."""
    return [paper.to_dict() for paper in pubmed_tool.search_pubmed(query, max_results)]


def query_adverse_events(drug_name: str, limit: int = 10) -> list[dict[str, Any]]:
    """Most-reported adverse reactions for a drug from the FDA FAERS database."""
    return openfda_tool.query_adverse_events(drug_name, limit)


def get_drug_label(drug_name: str) -> dict[str, Any]:
    """Key safety sections of the official FDA label for a drug."""
    return openfda_tool.get_drug_label(drug_name)


def search_trials(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search ClinicalTrials.gov for trials matching a query (plain dicts out)."""
    return [trial.to_dict() for trial in trials_tool.search_trials(query, max_results)]




def literature_rag(query: str, k: int = 5) -> Any:
    """Semantic search over the local FAISS index of medical papers.

    Graceful fallback: when no index has been built yet, returns an error
    dict (which the agent reports as a gap) instead of raising.
    """
    try:
        from rag import retrieve as rag_retrieve

        return rag_retrieve.retrieve(query, k=k)
    except (SystemExit, ImportError) as exc:  # missing index or slim deployment dependencies
        return {"error": f"literature_rag unavailable: {exc}"}


def query_faers_db(question: str) -> dict[str, Any]:
    """Text-to-SQL over the real openFDA snapshot, or the demo fallback."""
    from tools import sql_tool

    return sql_tool.query_faers_db(question)


# tool name -> (callable, one-line description shown to the planner LLM)
TOOLS: dict[str, tuple[Callable[..., Any], str]] = {
    "search_literature": (
        search_literature,
        "Search PubMed LIVE for recent papers on a drug, condition, or topic - best for 'recent literature' freshness",
    ),
    "query_adverse_events": (
        query_adverse_events,
        "Get the most-reported adverse events for a drug from the FDA FAERS database",
    ),
    "get_drug_label": (
        get_drug_label,
        "Get the official FDA label safety sections (warnings, adverse reactions) for a drug",
    ),
    "search_trials": (
        search_trials,
        "Search ClinicalTrials.gov for trials about a drug or condition",
    ),
    "literature_rag": (
        literature_rag,
        "Semantic search over the LOCAL PubMed abstract index (FAISS) for evidence passages - pair with search_literature on literature/evidence/studies questions",
    ),
    "query_faers_db": (
        query_faers_db,
        "Answer questions with SQL over a bounded snapshot of actual openFDA FAERS reports (synthetic demo fallback; counts not incidence)",
    ),
}
