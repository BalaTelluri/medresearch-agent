"""Reproducible, bounded MedQA USMLE four-option evaluation.

python -m eval.medqa_eval --n 50 --seed 42
python -m eval.medqa_eval --n 3 --seed 42 --judge   # more LLM calls

Accuracy is exact letter match, not medical validation. The optional custom
RAGAS-style judge is an LLM opinion, not the official RAGAS implementation.
"""
from __future__ import annotations

import config  # noqa: F401 - load local .env

import argparse
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATASET_NAME = "GBaker/MedQA-USMLE-4-options"
SPLIT = "test"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
LETTERS = "ABCD"


def load_questions(n: int, seed: int = 42) -> list[dict[str, Any]]:
    """Select n test rows with a fixed local RNG (no benchmark leakage)."""
    from datasets import load_dataset

    dataset = load_dataset(DATASET_NAME, split=SPLIT)
    if n < 1 or n > len(dataset):
        raise ValueError(f"--n must be between 1 and {len(dataset)}")
    indices = random.Random(seed).sample(range(len(dataset)), n)
    questions = []
    for idx in indices:
        row = dataset[idx]
        options = row["options"]
        if not isinstance(options, dict) or any(not isinstance(options.get(k), str) for k in LETTERS):
            raise ValueError(f"Unexpected options structure at test row {idx}")
        correct = str(row["answer_idx"]).strip().upper()
        if correct not in LETTERS:
            raise ValueError(f"Unexpected answer label at test row {idx}: {correct!r}")
        questions.append({"id": f"test-{idx}", "question": row["question"],
                          "options": {k: options[k] for k in LETTERS}, "correct": correct})
    return questions


def format_question(row: dict[str, Any]) -> str:
    choices = "\n".join(f"{key}. {row['options'][key]}" for key in LETTERS)
    return (f"{row['question']}\n\n{choices}\n\n"
            "Choose exactly one option (A, B, C, or D). Begin the final answer "
            "with 'Final answer: X' where X is the option letter, then explain your choice "
            "with evidence. If the tools do not cover this exam question, say so.")


def extract_choice(answer: str) -> str | None:
    """Avoid guessing from incidental letters in the body of a long answer."""
    patterns = [r"\bfinal\s+answer\s*[:\-]\s*\*{0,2}\(?([ABCD])\)?\b",
                r"\b(?:my\s+)?answer\s+is\s*[:\-]?\s*\*{0,2}\(?([ABCD])\)?\b",
                r"^\s*\*{0,2}\(?([ABCD])\)?[.):\s]", r"\b(?:option|choice)\s+([ABCD])\b"]
    for pattern in patterns:
        matches = re.findall(pattern, answer, flags=re.I | re.M)
        if matches:
            return matches[-1].upper()
    return None


def _retryable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(word in message for word in ("429", "rate limit", "too many requests", "temporarily unavailable", "503"))


def _infra_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(item in text for item in ("413", "request too large", "tokens per minute", "tpm", "tool choice is none", "tool_use_failed"))


def run_agent(row: dict[str, Any], attempts: int = 5, evidence_cap: int = 1500) -> dict:
    from agent.graph import run

    reduced = False
    for attempt in range(attempts):
        try:
            return run(format_question(row), eval_mode=True, evidence_cap=evidence_cap)
        except Exception as exc:
            text = str(exc).lower()
            if ("413" in text or "tokens per minute" in text or "tpm" in text) and not reduced:
                evidence_cap = 350
                reduced = True
                print("  TPM/context error: retrying once with 350 chars per tool after 60s.", flush=True)
                time.sleep(60)  # Reducing prompt size alone does not reset a per-minute quota.
                continue
            if ("tool choice is none" in text or "tool_use_failed" in text) and attempt < attempts - 1:
                print("  Model attempted a tool call; retrying once as text only.", flush=True)
                continue
            if not _retryable(exc) or attempt == attempts - 1:
                raise
            delay = min(60 * (attempt + 1), 180)
            print(f"  Rate limit / temporary failure. Retrying in {delay}s ({attempt + 1}/{attempts - 1}).", flush=True)
            time.sleep(delay)
    raise AssertionError("unreachable")


def majority(choices: list[str | None]) -> str | None:
    """Return the unique majority; ties and all-unanswered are abstentions."""
    counts = {letter: choices.count(letter) for letter in LETTERS}
    maximum = max(counts.values())
    winners = [letter for letter, count in counts.items() if count == maximum]
    return winners[0] if maximum and len(winners) == 1 else None


def _context_from_state(state: dict) -> str:
    """Use only returned tool evidence, never the gold exam answer as context."""
    items = []
    for name, result in state.get("tool_results", {}).items():
        if isinstance(result, dict) and "error" in result:
            continue
        items.append(f"{name}: {json.dumps(result, ensure_ascii=False, default=str)[:3000]}")
    return "\n".join(items)[:12000]


def score(results: list[dict]) -> dict:
    valid = [r for r in results if not r.get("error")]
    answered = [r for r in valid if r.get("chosen") in tuple(LETTERS)]
    correct = sum(r["chosen"] == r["correct"] for r in valid)
    judge = [r["judge"] for r in results if r.get("judge")]
    metrics = ("faithfulness", "answer_relevancy", "context_precision", "overall")
    return {"n": len(results), "valid": len(valid), "infra_errors": len(results) - len(valid),
            "answered": len(answered), "correct": correct,
            "accuracy_pct": round(100 * correct / len(valid), 2) if valid else 0,
            "answered_accuracy_pct": round(100 * correct / len(answered), 2) if answered else 0,
            "raw_accuracy_pct": round(100 * correct / len(results), 2) if results else 0,
            "judge_n": len(judge),
            "judge_means": {k: round(sum(j[k] for j in judge) / len(judge), 1) for k in metrics} if judge else None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", "--sample", dest="n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pace", type=float, default=12.0, help="minimum seconds between questions (default 12)")
    parser.add_argument("--vote", nargs="?", type=int, const=3, default=1, help="independent answers per question (bare --vote means 3)")
    parser.add_argument("--judge", action="store_true", help="run three extra LLM judge calls per question when tool evidence exists")
    args = parser.parse_args()
    if not 1 <= args.vote <= 5:
        parser.error("--vote must be between 1 and 5")
    if args.pace < 0:
        parser.error("--pace cannot be negative")
    rows = load_questions(args.n, args.seed)
    print(f"MedQA USMLE test: {args.n} sampled questions, seed {args.seed}; judge={'on' if args.judge else 'off'}", flush=True)
    results = []
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = RESULTS_DIR / f"medqa_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_n{args.n}_seed{args.seed}.json"
    for i, row in enumerate(rows, 1):
        started_question = time.monotonic()
        record = {"id": row["id"], "correct": row["correct"], "chosen": None,
                  "match": False, "tools_used": [], "judge": None, "error": None,
                  "votes": [], "vote_errors": []}
        states = []
        for vote_idx in range(args.vote):
            if vote_idx:
                time.sleep(args.pace)
            try:
                state = run_agent(row)
                states.append(state)
                record["votes"].append(extract_choice(state.get("answer", "")))
            except Exception as exc:
                record["votes"].append(None)
                record["vote_errors"].append(f"{type(exc).__name__}: {exc}"[:300])
        if states:
            record["chosen"] = majority(record["votes"])
            record["match"] = record["chosen"] == record["correct"]
            record["tools_used"] = sorted({line.split("(", 1)[0].replace("tool_router: ", "")
                for state in states for line in state.get("trace", []) if line.startswith("tool_router:")})
            state = states[0]
            if args.judge:
                context = _context_from_state(state)
                if context:
                    from rag.eval_judge import evaluate
                    try:
                        record["judge"] = evaluate(format_question(row), state.get("answer", ""), context)
                    except Exception as exc:
                        record["judge_skipped"] = f"judge call failed: {type(exc).__name__}: {exc}"[:200]
                else:
                    record["judge_skipped"] = "no successful tool evidence"
            record["answer"] = state.get("answer", "")
        else:
            record["error"] = "; ".join(record["vote_errors"])[:300] or "No completed vote"
        results.append(record)
        summary = score(results)
        output.write_text(json.dumps({"dataset": DATASET_NAME, "split": SPLIT,
            "n_requested": args.n, "seed": args.seed, "started_at_utc": started,
            "completed": len(results) == args.n, "summary": summary, "results": results},
            indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{i:>3}/{args.n} {row['id']:<12} chosen={str(record['chosen'] or '-'):1} "
              f"correct={row['correct']} {'ERROR' if record['error'] else ('PASS' if record['match'] else 'MISS')} "
              f"tools={','.join(record['tools_used']) or '-'}" +
              (f" error={record['error']}" if record['error'] else ""), flush=True)
        if i < len(rows):
            time.sleep(max(0, args.pace - (time.monotonic() - started_question)))
    summary = score(results)
    print("\nMedQA USMLE four-option TEST sample (exact option match)")
    print(f"Dataset: {DATASET_NAME} | n={args.n} | seed={args.seed}")
    print(f"Valid {summary['valid']}/{args.n} | Infrastructure errors {summary['infra_errors']} | "
          f"Answered {summary['answered']} | Correct {summary['correct']}")
    print(f"Accuracy on valid questions {summary['accuracy_pct']:.2f}% | "
          f"Answered-only {summary['answered_accuracy_pct']:.2f}% | "
          f"Raw correct/all {summary['raw_accuracy_pct']:.2f}%")
    print(f"Custom LLM judge: {summary['judge_n']}/{args.n} scored; mean metrics {summary['judge_means'] or 'not run'}")
    print(f"Saved: {output}")
    print("Exam-choice accuracy is not validation for patient care or pharmacovigilance.")


if __name__ == "__main__":
    main()
