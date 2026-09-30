"""LLM client with a swappable backend.

Primary backend is Groq's free tier. The default model is openai/gpt-oss-120b:
Groq retired the original default (llama-3.3-70b-versatile) on 2026-08-16 -
see https://console.groq.com/docs/deprecations. gpt-oss-120b follows the
JSON-only instructions the planner/cross_check prompts rely on. Override any
time with LLM_MODEL in .env. Set LLM_BACKEND=ollama to run fully local
through Ollama instead - weekend 3 swaps this again to vLLM serving the
fine-tuned model.

Environment:
    GROQ_API_KEY   required for the Groq backend (free at console.groq.com)
    LLM_BACKEND    "groq" (default) or "ollama"
    LLM_MODEL      override the model name for the active backend
"""


from __future__ import annotations
import config  # noqa: F401  (loads .env)

import os

GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"  # was llama-3.3-70b-versatile, retired 2026-08-16
OLLAMA_DEFAULT_MODEL = "llama3.3"
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def _backend() -> str:
    return os.environ.get("LLM_BACKEND", "groq").strip().lower()


def _chat_groq(messages: list[dict[str, str]], model: str) -> str:
    try:
        from groq import Groq
    except ImportError:
        raise SystemExit("Missing library. Run:  pip install groq")

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com "
            "and add it to your .env (see .env.example)."
        )
    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        tool_choice="none",
    )
    return completion.choices[0].message.content or ""


def _chat_ollama(messages: list[dict[str, str]], model: str) -> str:
    import requests

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={"model": model, "messages": messages, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def chat(messages: list[dict[str, str]], model: str | None = None) -> str:
    """Send a chat conversation to the active backend and return the reply text.

    messages: OpenAI-style [{"role": "system"|"user"|"assistant", "content": str}]
    """
    backend = _backend()
    if backend == "groq":
        return _chat_groq(messages, model or os.environ.get("LLM_MODEL", GROQ_DEFAULT_MODEL))
    if backend == "ollama":
        return _chat_ollama(messages, model or os.environ.get("LLM_MODEL", OLLAMA_DEFAULT_MODEL))
    raise ValueError(f"Unknown LLM_BACKEND {backend!r} - use 'groq' or 'ollama'.")


def complete(prompt: str, system: str | None = None) -> str:
    """Single-turn convenience wrapper around chat()."""
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    try:
        return chat(messages)
    except Exception as exc:
        message = str(exc).lower()
        if "tool choice is none" not in message and "tool_use_failed" not in message:
            raise
        # Some Groq models emit a pseudo-tool call despite no tools being supplied.
        # Try once more with a stricter instruction; never treat tool text as an answer.
        messages = ([{"role": "system", "content": (system or "") +
                    " Reply in plain text only. You have no tools. Never output a function call, JSON tool invocation, or search_browser."}]
                    if system else [{"role": "system", "content":
                    "Reply in plain text only. You have no tools. Never output a function call."}]) + [
                    {"role": "user", "content": prompt}]
        return chat(messages)


if __name__ == "__main__":
    # Smoke test: needs GROQ_API_KEY (or LLM_BACKEND=ollama with Ollama running).
    print(complete("Reply with exactly: backend ok"))


def complete_stream(prompt: str, system: str | None = None,
                    on_token=None) -> str:
    """Stream the answer when a callback is present, return full text.

    If streaming fails before any visible text, retry once as a buffered call.
    After visible text, propagate the error rather than silently duplicate or
    concatenate a different answer; the UI reports the interruption.
    """
    if on_token is None:
        return complete(prompt, system)
    messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}]
    parts = []
    try:
        if _backend() == "groq":
            from groq import Groq
            key = os.environ.get("GROQ_API_KEY", "").strip()
            if not key:
                raise ValueError("GROQ_API_KEY is not set")
            stream = Groq(api_key=key).chat.completions.create(
                model=os.environ.get("LLM_MODEL", GROQ_DEFAULT_MODEL),
                messages=messages, temperature=0.2, stream=True)
            for chunk in stream:
                text = chunk.choices[0].delta.content or ""
                if text:
                    parts.append(text)
                    on_token(text)
        elif _backend() == "ollama":
            import json
            import requests
            with requests.post(f"{OLLAMA_BASE_URL}/api/chat",
                               json={"model": os.environ.get("LLM_MODEL", OLLAMA_DEFAULT_MODEL),
                                     "messages": messages, "stream": True},
                               stream=True, timeout=120) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        text = json.loads(line).get("message", {}).get("content", "")
                        if text:
                            parts.append(text)
                            on_token(text)
        else:
            raise ValueError(f"Unknown LLM_BACKEND {_backend()!r}")
    except Exception:
        if parts:
            raise
        final = complete(prompt, system)
        on_token(final)
        return final
    return "".join(parts)
