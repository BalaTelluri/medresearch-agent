"""Build the FAISS literature index from real PubMed abstracts.

Fetches abstracts for the project's demo drug set through NCBI Entrez
(respects NCBI_EMAIL from .env), caches them to data/corpus/ so re-runs
skip the network entirely, then builds the FAISS index rag/retrieve.py
reads. After this, the agent's literature_rag tool goes live.

Run:
    python -m rag.build_index              # 50 abstracts per drug
    python -m rag.build_index --per-drug 100 --force
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

import argparse
import json
import time
from pathlib import Path

from rag import retrieve
from tools import pubmed_tool

DRUGS = [
    "semaglutide",
    "tirzepatide",
    "retatrutide",
    "metformin",
    "empagliflozin",
    "liraglutide",
]
CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "corpus" / "pubmed_abstracts.json"


def fetch_abstracts(per_drug: int, force: bool = False) -> list[dict]:
    """Fetch (or load from cache) abstracts for the demo drug set.

    Each document: {"text": "title\n\nabstract", "source": pubmed link}.
    Cached to disk - re-runs without --force never touch the network.
    """
    if CACHE_PATH.exists() and not force:
        docs = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        print(f"Corpus cache found: {len(docs)} abstracts (skipping PubMed fetch).")
        print("Use --force to re-download.")
        return docs

    print("Fetching abstracts from PubMed (NCBI Entrez)...")
    seen: set[str] = set()
    docs: list[dict] = []
    for i, drug in enumerate(DRUGS, start=1):
        query = f"{drug}[Title/Abstract] AND (safety[Title/Abstract] OR adverse[Title/Abstract] OR tolerability[Title/Abstract])"
        papers = pubmed_tool.search_pubmed(query, max_results=per_drug)
        fresh = 0
        for paper in papers:
            if paper.pmid in seen or not paper.abstract:
                continue
            seen.add(paper.pmid)
            docs.append({"text": f"{paper.title}\n\n{paper.abstract}", "source": paper.link})
            fresh += 1
        print(f"  [{i}/{len(DRUGS)}] {drug}: {fresh} abstracts")
        time.sleep(0.4)  # NCBI asks for <=3 requests/second without an API key

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(docs, indent=1), encoding="utf-8")
    print(f"Cached {len(docs)} abstracts to {CACHE_PATH}")
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-drug", type=int, default=50,
                        help="abstracts to fetch per drug (default 50)")
    parser.add_argument("--force", action="store_true", help="ignore the cache and re-fetch")
    args = parser.parse_args()

    docs = fetch_abstracts(args.per_drug, args.force)
    if not docs:
        raise SystemExit("No abstracts fetched - check NCBI_EMAIL in .env and your connection.")

    print("\nLoading the embedding model (first run downloads ~400 MB once)...")
    chunks = retrieve.build_index(docs)
    print(f"\nIndex built: {chunks} chunks from {len(docs)} abstracts.")
    print(f"Saved to {retrieve.INDEX_DIR}")
    print('Test it:  python -m rag.retrieve   or ask the agent - literature_rag is live now.')


if __name__ == "__main__":
    main()
