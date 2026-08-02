"""
Single shared LLM client wrapper. Every agent (Policy RAG, SQL Agent,
Action Agent, Router) goes through this module to call Claude — one place
to swap models, add tracing, and ensure we never leak the API key or full
prompts into client-facing responses.

Also the single choke point for AI-workflow observability: every call to
`complete()` (which `complete_json()` funnels through too) emits one
structured log line with model, latency, and token usage — regardless of
which agent triggered it — so instrumenting this one function gives
visibility into all four agents for free.

The Anthropic SDK call is blocking network I/O; call sites in the async
agents wrap these functions in `asyncio.to_thread(...)` so the event loop
isn't blocked.
"""
import json
import time
from typing import Any, Optional

import structlog
from anthropic import Anthropic

from app.core.config import settings

logger = structlog.get_logger("ai.llm_client")

_client: Optional[Anthropic] = None


def summarize_usage(usage_sink: list[dict]) -> dict:
    """Collapses a usage_sink populated across one or more `complete()`
    calls into totals suitable for a single audit log row."""
    return {
        "input_tokens": sum(u["input_tokens"] for u in usage_sink) or None,
        "output_tokens": sum(u["output_tokens"] for u in usage_sink) or None,
        "llm_call_count": len(usage_sink) or None,
        "llm_duration_ms": round(sum(u["duration_ms"] for u in usage_sink), 1) if usage_sink else None,
    }


def get_client() -> Anthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not configured. Set it in backend/.env before using AI features."
            )
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


def complete(
    system: str,
    user: str,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    usage_sink: Optional[list[dict]] = None,
) -> str:
    """`usage_sink`, if given, gets one {"input_tokens", "output_tokens",
    "duration_ms"} dict appended per real call — lets a caller that may make
    several LLM calls per request (e.g. SQL Agent's generate-then-summarize)
    aggregate total cost/latency to persist on a single audit log row. Plain
    list mutation, not a contextvar: this stays visible to the caller even
    though call sites run this via `asyncio.to_thread`, which would silently
    drop a contextvar write made inside the copied context."""
    client = get_client()
    started = time.perf_counter()
    try:
        resp = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except Exception as exc:
        logger.error(
            "llm_call_failed",
            model=settings.anthropic_model,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            error_type=type(exc).__name__,
        )
        raise

    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    text = "".join(block.text for block in resp.content if block.type == "text").strip()
    logger.info(
        "llm_call",
        model=settings.anthropic_model,
        duration_ms=duration_ms,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
        stop_reason=resp.stop_reason,
    )
    if usage_sink is not None:
        usage_sink.append(
            {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens, "duration_ms": duration_ms}
        )
    return text


def complete_json(
    system: str, user: str, max_tokens: int = 1024, usage_sink: Optional[list[dict]] = None
) -> dict[str, Any]:
    """Ask for ONLY JSON and parse it defensively. Used for intent
    classification, SQL generation, and action extraction."""
    strict_system = (
        system
        + "\n\nCRITICAL: Respond with ONLY a single valid JSON object. "
        "No markdown code fences, no preamble, no explanation text outside the JSON."
    )
    raw = complete(strict_system, user, max_tokens=max_tokens, temperature=0.0, usage_sink=usage_sink)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"LLM did not return valid JSON: {raw[:300]}")
