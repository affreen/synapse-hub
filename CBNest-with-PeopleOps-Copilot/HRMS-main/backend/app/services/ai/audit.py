"""
AI Audit Logging. Every /chat/* request writes exactly one row here,
regardless of outcome — auditability of refusals matters as much as
auditability of successful actions. Never persists: the raw JWT/access
token, passwords, bank/PAN fields, or full payroll figures. Does persist
request latency and LLM token usage (input/output/call count) so
cost/latency trends are queryable per user/role/tool over time.
"""
import json

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.ai_audit_log import AIAuditLog

MAX_MESSAGE_LEN = 1000


def pop_llm_usage(result: dict) -> dict:
    """Strips the internal `_llm_usage` key (summarized token/latency data
    from llm_client.summarize_usage) off an agent's result dict before it's
    sent to the client, returning it separately for the audit log."""
    usage = result.pop("_llm_usage", None) or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "llm_call_count": usage.get("llm_call_count"),
    }


def pop_refusal_reason(result: dict) -> str | None:
    """Strips the internal `_refusal_reason` guardrail code off an agent's
    result dict before it's sent to the client, returning it for the audit
    log and observability dashboard."""
    return result.pop("_refusal_reason", None)


async def write_audit_log(
    db: AsyncSession,
    user_id: int,
    role: str,
    message: str,
    intent: str | None = None,
    tool_name: str | None = None,
    action_status: str | None = None,
    records_accessed: list | None = None,
    latency_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    llm_call_count: int | None = None,
    refusal_reason: str | None = None,
) -> None:
    if not settings.ai_audit_log_enabled:
        return

    entry = AIAuditLog(
        user_id=user_id,
        role=role,
        message=message[:MAX_MESSAGE_LEN],
        intent=intent,
        tool_name=tool_name,
        action_status=action_status,
        records_accessed=json.dumps(records_accessed) if records_accessed else None,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        llm_call_count=llm_call_count,
        refusal_reason=refusal_reason,
    )
    db.add(entry)
    await db.commit()
