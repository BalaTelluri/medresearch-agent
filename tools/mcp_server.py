"""MCP server exposing every agent tool over one protocol.

This is the official MCP Python SDK (package `mcp`, FastMCP pattern) - the
same server shape job ads name. Each tool delegates to tools.registry, the
single import point, so the agent (direct imports today, MCP client calls
in weekend 2) and this server always expose identical behavior.

Run the server (stdio transport):
    python -m tools.mcp_server
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    raise SystemExit("Missing library. Run:  pip install -r requirements-full.txt")

from tools import registry

mcp = FastMCP("medresearch-agent")


@mcp.tool()
def search_literature(query: str, max_results: int = 5) -> list[dict]:
    """Search PubMed for papers matching a free-text query. Returns title,
    abstract, authors, publication date, and link per paper."""
    return registry.search_literature(query, max_results)


@mcp.tool()
def query_adverse_events(drug_name: str, limit: int = 10) -> list[dict]:
    """Most-reported adverse reactions for a drug from the live openFDA
    FAERS API, with report counts."""
    return registry.query_adverse_events(drug_name, limit)


@mcp.tool()
def get_drug_label(drug_name: str) -> dict:
    """Key safety sections (boxed warning, warnings, adverse reactions) of
    the official FDA drug label for a brand or generic name."""
    return registry.get_drug_label(drug_name)


@mcp.tool()
def search_trials(query: str, max_results: int = 5) -> list[dict]:
    """Search ClinicalTrials.gov for trials matching a free-text query."""
    return registry.search_trials(query, max_results)


@mcp.tool()
def literature_rag(query: str, k: int = 5) -> Any:
    """Semantic search over the local FAISS index of medical papers. Needs
    an index built with rag.retrieve.build_index; returns an error note
    when none exists."""
    return registry.literature_rag(query, k)


@mcp.tool()
def query_faers_db(question: str) -> dict:
    """Answer a natural-language question with read-only SQL over the local
    FAERS openFDA snapshot, or synthetic demo fallback if absent."""
    return registry.query_faers_db(question)


if __name__ == "__main__":
    mcp.run()
