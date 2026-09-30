"""RAGAS-style LLM-as-judge evaluation for the retrieval layer.

Adapted from FinSight (utils/ragas_eval.py): same three metrics, same
prompts, same 0.4/0.4/0.2 weighted overall. Changed for this project: the
Groq SDK client is replaced by agent.llm_client.complete() so the backend
stays swappable (Groq now, Ollama/vLLM later). The `ragas` package in
requirements-full.txt adds the reference implementation in weekend 2; this
judge stays as the lightweight in-loop check.
"""

from __future__ import annotations

import config  # noqa: F401  (loads .env)

from agent import llm_client

# Prompts carried over from FinSight's utils/ragas_eval.py, unchanged.
FAITHFULNESS_PROMPT = """You are evaluating an AI answer for faithfulness.

FAITHFULNESS means: Is every claim in the answer supported by the context?
Score from 0.0 to 1.0:
- 1.0 = Every claim is directly supported by context
- 0.5 = Some claims supported, some not
- 0.0 = Answer contains claims not in context (hallucination)

Context:
{context}

Answer:
{answer}

Respond with ONLY a number between 0.0 and 1.0. Nothing else."""

RELEVANCY_PROMPT = """You are evaluating an AI answer for relevancy.

ANSWER RELEVANCY means: Does the answer directly address the question asked?
Score from 0.0 to 1.0:
- 1.0 = Answer perfectly addresses the question
- 0.5 = Answer partially addresses the question
- 0.0 = Answer is off-topic or does not address the question

Question:
{question}

Answer:
{answer}

Respond with ONLY a number between 0.0 and 1.0. Nothing else."""

CONTEXT_PRECISION_PROMPT = """You are evaluating retrieved context for precision.

CONTEXT PRECISION means: Is the retrieved context relevant to the question?
Score from 0.0 to 1.0:
- 1.0 = All retrieved context is highly relevant to the question
- 0.5 = Some context is relevant, some is not
- 0.0 = Retrieved context is not relevant to the question

Question:
{question}

Retrieved Context:
{context}

Respond with ONLY a number between 0.0 and 1.0. Nothing else."""


def _get_score(prompt: str) -> float:
    """Ask the LLM for a single 0.0-1.0 score; unparseable replies score 0."""
    try:
        score = float(llm_client.complete(prompt).strip())
    except (ValueError, TypeError):
        return 0.0
    return round(min(max(score, 0.0), 1.0), 2)


def evaluate(question: str, answer: str, context: str) -> dict[str, float]:
    """Score faithfulness, relevancy, and context precision (percentages)."""
    faithfulness = _get_score(FAITHFULNESS_PROMPT.format(context=context, answer=answer))
    relevancy = _get_score(RELEVANCY_PROMPT.format(question=question, answer=answer))
    precision = _get_score(CONTEXT_PRECISION_PROMPT.format(question=question, context=context))
    overall = round((faithfulness * 0.4 + relevancy * 0.4 + precision * 0.2), 2)

    return {
        "faithfulness": round(faithfulness * 100, 1),
        "answer_relevancy": round(relevancy * 100, 1),
        "context_precision": round(precision * 100, 1),
        "overall": round(overall * 100, 1),
    }
