import time
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import error_response, success_response
from app.db.session import get_db
from app.models.ai_audit_log import AIAuditLog
from app.models.employee import Employee
from app.models.enums import Role
from app.schemas.chat import ChatMessageCreate, ChatRequest, ChatSessionCreate
from app.services.auth import get_current_user, oauth2_scheme, require_roles
from app.services.ai import action_agent, audit, graph, policy_rag, router_agent, sql_agent

router = APIRouter()
logger = structlog.get_logger("ai.chat")

# refusal_reason codes that mean "this user/role wasn't allowed to see or do
# this", as opposed to a structurally-invalid request. Sourced from
# services/ai/action_agent.py (PERMISSION_DENIED) and the role-scope check in
# services/ai/sql_agent.py (ROLE_SCOPE_VIOLATION) — kept separate from
# SQL_BLOCKED_REFUSAL_REASONS below, which is what sql_guardrails.validate_sql
# itself rejects regardless of role.
PERMISSION_REFUSAL_REASONS = {"PERMISSION_DENIED", "ROLE_SCOPE_VIOLATION"}

# refusal_reason codes produced by services/ai/sql_guardrails.validate_sql —
# a generated query rejected by the guardrail layer (destructive/multi-statement/
# non-SELECT/forbidden-column/etc.), independent of who asked.
SQL_BLOCKED_REFUSAL_REASONS = {
    "FORBIDDEN_COLUMN",
    "BLOCKED_KEYWORD",
    "NOT_SELECT",
    "MULTIPLE_STATEMENTS",
    "EMPTY_SQL",
    "DISALLOWED_SYNTAX",
    "DISALLOWED_TABLE",
}




@router.post("/sessions")
async def create_chat_session(
    payload: ChatSessionCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Chat session creation is a Phase-3 stub and not implemented yet"),
    )


@router.post("/sessions/{session_id}/messages")
async def post_chat_message(
    session_id: str,
    payload: ChatMessageCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = session_id
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Chat messaging is a Phase-3 stub and not implemented yet"),
    )


# ---------------------------------------------------------------------------
# PeopleOps Copilot — Policy RAG / SQL Agent / HR Action Agent / Router
# ---------------------------------------------------------------------------


@router.post("/policy")
async def chat_policy(
    payload: ChatRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    started = time.perf_counter()
    try:
        result = await policy_rag.answer_policy_question(db, payload.message)
        status_ = "SUCCESS" if result["sources"] else "NO_ANSWER"
        usage = audit.pop_llm_usage(result)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        await audit.write_audit_log(
            db,
            user_id=current_user.id,
            role=current_user.role.value,
            message=payload.message,
            intent="POLICY_QA",
            tool_name="policy_rag",
            action_status=status_,
            latency_ms=duration_ms,
            **usage,
        )
        logger.info(
            "chat_request", intent="POLICY_QA", user_id=current_user.id, role=current_user.role.value,
            action_status=status_, sources_count=len(result["sources"]), duration_ms=duration_ms, **usage,
        )
        return success_response(result)
    except Exception as exc:
        await audit.write_audit_log(
            db, user_id=current_user.id, role=current_user.role.value, message=payload.message,
            intent="POLICY_QA", tool_name="policy_rag", action_status="ERROR",
        )
        logger.error(
            "chat_request_failed", intent="POLICY_QA", user_id=current_user.id, role=current_user.role.value,
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response("POLICY_ASSISTANT_UNAVAILABLE", "The policy assistant is temporarily unavailable."),
        )


@router.post("/sql")
async def chat_sql(
    payload: ChatRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    started = time.perf_counter()
    try:
        result = await sql_agent.generate_and_run_sql(db, payload.message, current_user.id, current_user.role.value)
        status_ = "SUCCESS" if result.get("sql") else "REFUSED"
        usage = audit.pop_llm_usage(result)
        refusal_reason = audit.pop_refusal_reason(result)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        await audit.write_audit_log(
            db,
            user_id=current_user.id,
            role=current_user.role.value,
            message=payload.message,
            intent="SQL_QUERY",
            tool_name="sql_agent",
            action_status=status_,
            records_accessed=[r.get("id") for r in result.get("rows", []) if isinstance(r, dict) and "id" in r],
            latency_ms=duration_ms,
            refusal_reason=refusal_reason,
            **usage,
        )
        logger.info(
            "chat_request", intent="SQL_QUERY", user_id=current_user.id, role=current_user.role.value,
            action_status=status_, row_count=len(result.get("rows", [])), duration_ms=duration_ms,
            refusal_reason=refusal_reason, **usage,
        )
        return success_response(result)
    except Exception as exc:
        await audit.write_audit_log(
            db, user_id=current_user.id, role=current_user.role.value, message=payload.message,
            intent="SQL_QUERY", tool_name="sql_agent", action_status="ERROR",
        )
        logger.error(
            "chat_request_failed", intent="SQL_QUERY", user_id=current_user.id, role=current_user.role.value,
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response("DATA_ASSISTANT_UNAVAILABLE", "The data assistant is temporarily unavailable."),
        )


@router.post("/actions")
async def chat_actions(
    payload: ChatRequest,
    current_user: Employee = Depends(get_current_user),
    access_token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    started = time.perf_counter()
    try:
        result = await action_agent.handle_action_request(
            message=payload.message,
            pending_action=payload.pending_action,
            user_id=current_user.id,
            role=current_user.role.value,
            access_token=access_token,
        )
        usage = audit.pop_llm_usage(result)
        refusal_reason = audit.pop_refusal_reason(result)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        await audit.write_audit_log(
            db,
            user_id=current_user.id,
            role=current_user.role.value,
            message=payload.message,
            intent="HR_ACTION",
            tool_name=result.get("tool_called"),
            action_status=result.get("action_status"),
            latency_ms=duration_ms,
            refusal_reason=refusal_reason,
            **usage,
        )
        logger.info(
            "chat_request", intent="HR_ACTION", user_id=current_user.id, role=current_user.role.value,
            tool_name=result.get("tool_called"), action_status=result.get("action_status"),
            duration_ms=duration_ms, refusal_reason=refusal_reason, **usage,
        )
        return success_response(result)
    except Exception as exc:
        await audit.write_audit_log(
            db, user_id=current_user.id, role=current_user.role.value, message=payload.message,
            intent="HR_ACTION", tool_name=None, action_status="ERROR",
        )
        logger.error(
            "chat_request_failed", intent="HR_ACTION", user_id=current_user.id, role=current_user.role.value,
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response("ACTION_ASSISTANT_UNAVAILABLE", "The action assistant is temporarily unavailable."),
        )


@router.post("/graph")
async def chat_graph(
    payload: ChatRequest,
    current_user: Employee = Depends(get_current_user),
    access_token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Unified entry point running the LangGraph pipeline (see
    services/ai/graph.py): load user context -> classify intent -> route to
    Policy RAG / SQL Agent / HR Action Agent -> permission check -> generate
    response -> audit log. Additive to /chat/policy, /chat/sql, /chat/actions
    (which stay mode-tab-driven) - this is the auto-routed alternative."""
    try:
        result = await graph.run_graph(
            db=db,
            message=payload.message,
            pending_action=payload.pending_action,
            user_id=current_user.id,
            role=current_user.role.value,
            access_token=access_token,
        )
        return success_response(result)
    except Exception as exc:
        await audit.write_audit_log(
            db, user_id=current_user.id, role=current_user.role.value, message=payload.message,
            intent="GRAPH", tool_name=None, action_status="ERROR",
        )
        logger.error(
            "chat_graph_failed", user_id=current_user.id, role=current_user.role.value,
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response("GRAPH_ASSISTANT_UNAVAILABLE", "The unified assistant is temporarily unavailable."),
        )


@router.post("/router")
async def chat_router(
    payload: ChatRequest,
    current_user: Employee = Depends(get_current_user),
):
    started = time.perf_counter()
    try:
        result = await router_agent.classify_intent(payload.message)
        logger.info(
            "chat_request", intent="ROUTER", user_id=current_user.id, role=current_user.role.value,
            classified_intent=result.get("intent"), confidence=result.get("confidence"),
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return success_response(result)
    except Exception as exc:
        logger.error(
            "chat_request_failed", intent="ROUTER", user_id=current_user.id, role=current_user.role.value,
            error_type=type(exc).__name__,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response("ROUTER_UNAVAILABLE", "The router is temporarily unavailable."),
        )


@router.get("/observability")
async def chat_observability(
    days: int = 14,
    _: Employee = Depends(require_roles(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only aggregate view over ai_audit_logs: request volume, LLM
    token/latency cost, and outcome breakdown by intent/tool/day. Backs the
    AI Observability dashboard (/ai-copilot/observability in the app)."""
    days = max(1, min(days, 90))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    where_clause = AIAuditLog.created_at >= since

    totals = (
        await db.execute(
            select(
                func.count(AIAuditLog.id),
                func.avg(AIAuditLog.latency_ms),
                func.sum(AIAuditLog.input_tokens),
                func.sum(AIAuditLog.output_tokens),
                func.sum(AIAuditLog.llm_call_count),
            ).where(where_clause)
        )
    ).one()
    total_requests, avg_latency_ms, total_input_tokens, total_output_tokens, total_llm_calls = totals

    by_intent = (
        await db.execute(
            select(
                AIAuditLog.intent,
                func.count(AIAuditLog.id),
                func.avg(AIAuditLog.latency_ms),
                func.sum(AIAuditLog.input_tokens),
                func.sum(AIAuditLog.output_tokens),
            )
            .where(where_clause)
            .group_by(AIAuditLog.intent)
            .order_by(func.count(AIAuditLog.id).desc())
        )
    ).all()

    by_status = (
        await db.execute(
            select(AIAuditLog.action_status, func.count(AIAuditLog.id))
            .where(where_clause)
            .group_by(AIAuditLog.action_status)
            .order_by(func.count(AIAuditLog.id).desc())
        )
    ).all()

    by_tool = (
        await db.execute(
            select(AIAuditLog.tool_name, func.count(AIAuditLog.id))
            .where(where_clause, AIAuditLog.tool_name.is_not(None))
            .group_by(AIAuditLog.tool_name)
            .order_by(func.count(AIAuditLog.id).desc())
            .limit(10)
        )
    ).all()

    by_role = (
        await db.execute(
            select(AIAuditLog.role, func.count(AIAuditLog.id))
            .where(where_clause)
            .group_by(AIAuditLog.role)
            .order_by(func.count(AIAuditLog.id).desc())
        )
    ).all()

    by_refusal_reason = (
        await db.execute(
            select(AIAuditLog.refusal_reason, func.count(AIAuditLog.id))
            .where(where_clause, AIAuditLog.refusal_reason.is_not(None))
            .group_by(AIAuditLog.refusal_reason)
            .order_by(func.count(AIAuditLog.id).desc())
        )
    ).all()

    # Derived headline metrics — computed from queries already run above
    # (by_intent, by_refusal_reason) rather than issuing new round trips,
    # except for the one count that isn't broken out anywhere yet.
    failed_permission_attempts = sum(count for reason, count in by_refusal_reason if reason in PERMISSION_REFUSAL_REASONS)
    sql_blocked_query_count = sum(count for reason, count in by_refusal_reason if reason in SQL_BLOCKED_REFUSAL_REASONS)

    policy_no_answer_count = (
        await db.execute(
            select(func.count(AIAuditLog.id)).where(
                where_clause, AIAuditLog.intent == "POLICY_QA", AIAuditLog.action_status == "NO_ANSWER"
            )
        )
    ).scalar() or 0
    policy_total = next((count for intent, count, *_ in by_intent if intent == "POLICY_QA"), 0)
    rag_no_answer_rate_pct = round(100 * policy_no_answer_count / policy_total, 1) if policy_total else None

    daily_bucket = func.date(AIAuditLog.created_at)
    daily = (
        await db.execute(
            select(
                daily_bucket,
                func.count(AIAuditLog.id),
                func.avg(AIAuditLog.latency_ms),
                func.sum(AIAuditLog.input_tokens),
                func.sum(AIAuditLog.output_tokens),
            )
            .where(where_clause)
            .group_by(daily_bucket)
            .order_by(daily_bucket)
        )
    ).all()

    return success_response(
        {
            "since": since.isoformat(),
            "days": days,
            "totals": {
                "total_requests": total_requests or 0,
                "avg_latency_ms": round(avg_latency_ms, 1) if avg_latency_ms else None,
                "total_input_tokens": total_input_tokens or 0,
                "total_output_tokens": total_output_tokens or 0,
                "total_llm_calls": total_llm_calls or 0,
                "failed_permission_attempts": failed_permission_attempts,
                "sql_blocked_query_count": sql_blocked_query_count,
                "rag_no_answer_rate_pct": rag_no_answer_rate_pct,
            },
            "by_intent": [
                {
                    "intent": intent or "UNKNOWN",
                    "count": count,
                    "avg_latency_ms": round(avg_ms, 1) if avg_ms else None,
                    "input_tokens": in_tok or 0,
                    "output_tokens": out_tok or 0,
                }
                for intent, count, avg_ms, in_tok, out_tok in by_intent
            ],
            "by_status": [{"status": s or "UNKNOWN", "count": c} for s, c in by_status],
            "by_tool": [{"tool_name": t, "count": c} for t, c in by_tool],
            "by_role": [{"role": r, "count": c} for r, c in by_role],
            "by_refusal_reason": [{"reason": r, "count": c} for r, c in by_refusal_reason],
            "daily": [
                {
                    "date": d,
                    "count": count,
                    "avg_latency_ms": round(avg_ms, 1) if avg_ms else None,
                    "input_tokens": in_tok or 0,
                    "output_tokens": out_tok or 0,
                }
                for d, count, avg_ms, in_tok, out_tok in daily
            ],
        }
    )

