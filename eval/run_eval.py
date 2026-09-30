"""MedQA-style evaluation harness: run the agent over bundled sample
questions and score the answers.

Three heuristic scores per question (no extra API calls):
- citations: does the answer carry inline [n] citations or source links?
- contradictions: did cross_check flag source disagreements (when true)?
- keyword coverage: fraction of the reference keywords found in the answer.

The bundled SAMPLE is a small MedQA-style set written for this project -
swap in the real benchmark (eval/medqa_eval.py, GBaker/MedQA-USMLE-4-options)
in weekend 3. Prints one row per question plus a summary line - screenshot
that table for the portfolio.

Run:
    python -m eval.run_eval
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

import re
from typing import Any

# MedQA-style sample written for this project (not the USMLE benchmark).
# keywords: terms a correct answer should mention (case-insensitive).
SAMPLE: list[dict[str, Any]] = [
    {
        "question": "Which adverse events are most reported for metformin, and what is its boxed warning?",
        "keywords": ["nausea", "diarrhoea", "lactic acidosis"],
    },
    {
        "question": "What are the most common adverse events reported for semaglutide?",
        "keywords": ["nausea", "vomiting"],
    },
    {
        "question": "Is pancreatitis a labeled risk of GLP-1 receptor agonists like tirzepatide?",
        "keywords": ["pancreatitis"],
    },
    {
        "question": "What does recent literature say about metformin-associated lactic acidosis risk?",
        "keywords": ["lactic acidosis", "renal"],
    },
    {
        "question": "Are there recruiting clinical trials for retatrutide?",
        "keywords": ["trial"],
    },
    {
        "question": "Compare the adverse-event profiles of semaglutide and tirzepatide.",
        "keywords": ["nausea", "diarrhoea"],
    },
]


def has_citations(answer: str) -> bool:
    """True when the answer carries inline [n] citations or source links."""
    return bool(re.search(r"\[\d+\]", answer)) or "http" in answer


def keyword_coverage(answer: str, keywords: list[str]) -> float:
    """Fraction of reference keywords present in the answer (case-insensitive)."""
    if not keywords:
        return 1.0
    found = sum(1 for kw in keywords if kw.lower() in answer.lower())
    return round(found / len(keywords), 2)


def verdict(cited: bool, coverage: float) -> str:
    if cited and coverage >= 0.5:
        return "PASS"
    if cited or coverage >= 0.5:
        return "PARTIAL"
    return "FAIL"


def main() -> None:
    from agent.graph import run

    print(f"MedQA-style sample eval - {len(SAMPLE)} questions\n")
    rows = []
    for i, item in enumerate(SAMPLE, start=1):
        print(f"[{i}/{len(SAMPLE)}] {item['question'][:70]}...")
        state = run(item["question"])
        answer = state.get("answer", "")
        cited = has_citations(answer)
        coverage = keyword_coverage(answer, item["keywords"])
        contradictions = len(state.get("contradictions", []))
        tools = [t.split("(")[0].replace("tool_router: ", "")
                 for t in state.get("trace", []) if t.startswith("tool_router:")]
        rows.append({
            "question": item["question"],
            "cited": cited,
            "coverage": coverage,
            "contradictions": contradictions,
            "tools": sorted(set(tools)),
            "verdict": verdict(cited, coverage),
        })

    print("\n" + "=" * 78)
    print(f"{'#':<3}{'cited':<7}{'keywords':<10}{'contra':<8}{'verdict':<9}question")
    print("-" * 78)
    for i, r in enumerate(rows, start=1):
        print(f"{i:<3}{str(r['cited']):<7}{r['coverage']:<10}{r['contradictions']:<8}"
              f"{r['verdict']:<9}{r['question'][:38]}")
    passed = sum(1 for r in rows if r["verdict"] == "PASS")
    print("-" * 78)
    print(f"PASS {passed}/{len(rows)}   "
          f"mean keyword coverage {sum(r['coverage'] for r in rows) / len(rows):.2f}   "
          f"tools used: {sorted({t for r in rows for t in r['tools']})}")
    print("=" * 78)
    print("\nHeuristic scores (citations, keyword coverage) - weekend 3 adds the")
    print("real MedQA benchmark + RAGAS via eval/medqa_eval.py and rag/eval_judge.py.")


if __name__ == "__main__":
    main()
