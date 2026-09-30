"""FAISS retrieval layer for the medical paper corpus.

Adapted from FinSight (github.com/BalaTelluri/FinSight-AI-Powered-Financial-
Document-Assistant-RAG-System-, utils/rag_pipeline.py + document_loader.py).
What came from FinSight:
- normalized sentence-transformers embeddings (all-mpnet-base-v2, cpu)
- recursive character chunking, chunk_size 400 / overlap 80
- L2 similarity search, merge + dedupe of results by content prefix
- the sigmoid L2-distance -> confidence conversion

What changed for this project:
- langchain dropped: plain sentence-transformers + faiss (already in
  requirements-full.txt), no new dependencies
- one medical-corpus index persisted to disk instead of per-domain
  in-memory indexes (FinSight's per-domain split returns in weekend 2
  when the FAERS SQLite database lands)
- sources are paper titles/links so the answer node can cite them
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

import json
from pathlib import Path
from typing import Any

INDEX_DIR = Path(__file__).resolve().parent.parent / "data" / "faiss_index"
EMBEDDING_MODEL = "sentence-transformers/all-mpnet-base-v2"  # FinSight's model
EMBED_BATCH_SIZE = 16  # modest batches keep the Apple Silicon encode path stable
CHUNK_SIZE = 400      # FinSight splitter settings
CHUNK_OVERLAP = 80


def _load_stack():
    """Import the heavy RAG stack lazily, with beginner-proof errors.

    Apple Silicon guard: sentence-transformers + torch can segfault during
    encode on macOS when the tokenizers/OpenMP thread pools collide (python.org
    framework builds hit this). The env pins below must be set BEFORE torch
    loads - this function is the only import site, so they always win.
    Device stays CPU everywhere (MPS is the other crash source).
    """
    import os

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    try:
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise SystemExit(
            "Missing RAG libraries. Run:  pip install -r requirements-full.txt"
        )
    return faiss, np, SentenceTransformer


def _split_text(text: str) -> list[str]:
    """Recursive character splitting, ported from FinSight's document_loader.

    Tries paragraph, line, sentence, then word boundaries so chunks stay
    under CHUNK_SIZE with CHUNK_OVERLAP characters of carry-over context.
    """
    text = text.strip()
    if len(text) <= CHUNK_SIZE:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(sep, start + CHUNK_OVERLAP, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = max(end - CHUNK_OVERLAP, start + 1) if end < len(text) else len(text)
    return chunks


def build_index(documents: list[Any], index_dir: Path = INDEX_DIR) -> int:
    """Embed documents and write a FAISS index to disk. Returns chunk count.

    documents: plain strings, or dicts {"text": ..., "source": ...} where
    source is the paper title or link the answer node cites.
    """
    faiss, np, SentenceTransformer = _load_stack()

    rows: list[dict[str, str]] = []
    for i, doc in enumerate(documents):
        text, source = (doc.get("text", ""), doc.get("source", "")) if isinstance(doc, dict) else (str(doc), f"doc-{i}")
        for chunk in _split_text(text):
            rows.append({"text": chunk, "source": source})
    if not rows:
        raise ValueError("build_index: no text to index.")

    model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    vectors = model.encode(
        [r["text"] for r in rows],
        batch_size=EMBED_BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    index = faiss.IndexFlatL2(vectors.shape[1])
    index.add(np.asarray(vectors, dtype="float32"))

    index_dir.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(index_dir / "index.faiss"))
    with open(index_dir / "chunks.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return len(rows)


def confidence_from_scores(scores: list[float]) -> float:
    """FinSight's sigmoid L2-distance -> confidence percentage.

    0.0 -> 100%, 0.5 -> 85%, 1.0 -> 60%, 2.0 -> 20% (lower distance = better).
    """
    if not scores:
        return 0.0
    best = min(scores)
    return round(min(max(100.0 / (1.0 + best), 0.0), 100.0), 1)


def retrieve(query: str, k: int = 5, index_dir: Path = INDEX_DIR) -> list[dict]:
    """Return the k most relevant chunks for a query.

    Each result: {"text": str, "source": str, "score": float} where score is
    the FAISS L2 distance (lower = more relevant). The "source" field carries
    the paper title or link - the answer node turns it into the citation.
    """
    faiss, np, SentenceTransformer = _load_stack()

    index_path = index_dir / "index.faiss"
    chunks_path = index_dir / "chunks.jsonl"
    if not index_path.exists() or not chunks_path.exists():
        raise SystemExit(
            f"No FAISS index at {index_dir}. Build it first: "
            "python -m rag.build_corpus (or rag.retrieve.build_index(...))."
        )

    index = faiss.read_index(str(index_path))
    with open(chunks_path, encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh]

    model = SentenceTransformer(EMBEDDING_MODEL, device="cpu")
    qvec = np.asarray(
        model.encode([query], normalize_embeddings=True, show_progress_bar=False),
        dtype="float32",
    )
    distances, ids = index.search(qvec, min(k * 2, len(rows)))

    # FinSight merge rule: dedupe by content prefix, keep best score first.
    seen: set[str] = set()
    results: list[dict] = []
    for dist, idx in zip(distances[0], ids[0]):
        if idx < 0:
            continue
        row = rows[int(idx)]
        key = row["text"][:100]
        if key in seen:
            continue
        seen.add(key)
        results.append({"text": row["text"], "source": row["source"], "score": float(dist)})
        if len(results) >= k:
            break
    return results


if __name__ == "__main__":
    # Smoke test: index two toy abstracts, retrieve, print. Needs the full
    # requirements installed (sentence-transformers downloads the model once).
    docs = [
        {"text": "Metformin is a first-line therapy for type 2 diabetes. "
                 "Rare cases of metformin-associated lactic acidosis occur, "
                 "mainly with renal impairment or overdose.",
         "source": "Toy safety abstract"},
        {"text": "SGLT2 inhibitors reduce cardiovascular events in diabetic "
                 "patients with established heart disease.",
         "source": "Toy cardio abstract"},
    ]
    n = build_index(docs, index_dir=Path("/tmp/mra_toy_index"))
    print(f"Indexed {n} chunks.")
    for hit in retrieve("metformin lactic acidosis risk", k=2, index_dir=Path("/tmp/mra_toy_index")):
        print(f"  {hit['score']:.3f}  [{hit['source']}] {hit['text'][:80]}...")
