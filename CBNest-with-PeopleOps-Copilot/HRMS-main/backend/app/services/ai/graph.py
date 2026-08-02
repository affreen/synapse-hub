"""
LangGraph-orchestrated unified entry point for the PeopleOps Copilot.

    START -> load_user_context -> classify_intent -> route ->
      { policy_rag_node | sql_agent_node | hr_action_node | unhandled_node } ->
      permission_check -> generate_final_response -> audit_log -> END

This is additive, not a replacement: /chat/policy, /chat/sql, /chat/actions
stay exactly as they are (the frontend's mode tabs pick the agent directly,
no classification needed there). This graph exists for POST /chat/graph, a
single free-form entry point where intent is classified automatically
instead of chosen by the UI.

No business logic is duplicated here — every node is a thin wrapper around
the same policy_rag / sql_agent / action_agent / permissions / audit
modules the three existing endpoints already use and that already have
test + eval coverage. The graph's job is orchestration and one extra
defense-in-depth checkpoint (permission_check), not reimplementing
guardrails.
"""
import time
from typing import TypedDict

import structlog
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.services.ai import action_agent, audit, policy_rag, router_agent, sql_agent
from app.services.ai.permissions import is_tool_permitted, permission_denied_message

logger = structlog.get_logger("ai.graph")

_INTENT_TO_NODE = {
    "POLICY_QA": "policy_rag_node",
    "SQL_QUERY": "sql_agent_node",
    "HR_ACTION": "hr_action_node",
}


class GraphState(TypedDict, total=False):
    # inputs, set once before the graph runs
    message: str
    pending_action: dict | None
    user_id: int
    access_token: str
    db: AsyncSession
    started_at: float
    # populated by load_user_context (falls back to the caller-supplied
    # value below if the employee can't be re-fetched for some reason)
    role: str
    # populated by classify_intent
    intent: str
    intent_confidence: float | None
    router_usage: list[dict]
    # populated by the routed agent node / permission_check
    agent_result: dict
    # populated by generate_final_response
    final_response: dict


async def _load_user_context(state: GraphState) -> dict:
    """Re-fetches the employee from the DB rather than trusting only the
    role baked into the caller's JWT — keeps the graph self-contained and
    correct even if a role change hasn't been reflected in a still-valid
    token yet."""
    result = await state["db"].execute(select(Employee).where(Employee.id == state["user_id"]))
    employee = result.scalar_one_or_none()
    if employee is None:
        return {}
    return {"role": employee.role.value}


async def _classify_intent(state: GraphState) -> dict:
    # A yes/no reply to a pending high-impact-action confirmation always
    # continues the HR Action Agent's confirmation flow — never worth
    # re-classifying (and the model has no way to know it's a reply).
    if state.get("pending_action"):
        return {"intent": "HR_ACTION", "intent_confidence": 1.0}

    usage_sink: list[dict] = []
    result = await router_agent.classify_intent(state["message"], usage_sink=usage_sink)
    return {"intent": result["intent"], "intent_confidence": result.get("confidence"), "router_usage": usage_sink}


def _route(state: GraphState) -> str:
    return _INTENT_TO_NODE.get(state["intent"], "unhandled_node")


async def _policy_rag_node(state: GraphState) -> dict:
    result = await policy_rag.answer_policy_question(state["db"], state["message"])
    return {"agent_result": result}


async def _sql_agent_node(state: GraphState) -> dict:
    result = await sql_agent.generate_and_run_sql(state["db"], state["message"], state["user_id"], state["role"])
    return {"agent_result": result}


async def _hr_action_node(state: GraphState) -> dict:
    result = await action_agent.handle_action_request(
        message=state["message"],
        pending_action=state.get("pending_action"),
        user_id=state["user_id"],
        role=state["role"],
        access_token=state["access_token"],
    )
    return {"agent_result": result}


async def _unhandled_node(state: GraphState) -> dict:
    return {
        "agent_result": {
            "answer": "I'm not sure how to help with that. Try asking a policy question, a data lookup, or an HR task.",
        }
    }


async def _permission_check(state: GraphState) -> dict:
    """Defense-in-depth checkpoint, not a second independent implementation:
    policy_rag/sql_agent already enforce their own guardrails internally
    (column/table/role-scope), and action_agent already checks
    is_tool_permitted before ever executing a tool. This re-verifies that
    same permission for whatever tool_called came back, using the exact
    same permissions.py action_agent used internally — so a bug that let an
    unpermitted tool_called slip through gets caught here too, instead of
    the system trusting a single code path."""
    result = state["agent_result"]
    tool_called = result.get("tool_called")
    if tool_called and not is_tool_permitted(tool_called, state["role"]):
        logger.warning(
            "graph_permission_check_blocked", role=state["role"], user_id=state["user_id"], tool_name=tool_called
        )
        return {
            "agent_result": {
                **result,
                "answer": permission_denied_message(tool_called),
                "action_status": "REFUSED",
                "_refusal_reason": "PERMISSION_DENIED",
            }
        }
    return {}


async def _generate_final_response(state: GraphState) -> dict:
    """Normalizes the differently-shaped policy/SQL/action results into one
    response envelope for the unified endpoint."""
    result = state["agent_result"]
    final = {
        "answer": result.get("answer", ""),
        "intent": state["intent"],
        "sources": result.get("sources"),
        "sql": result.get("sql"),
        "rows": result.get("rows"),
        "tool_called": result.get("tool_called"),
        "action_status": result.get("action_status"),
        "result": result.get("result"),
        "requires_confirmation": result.get("requires_confirmation", False),
        "pending_action": result.get("pending_action"),
    }
    return {"final_response": final}


async def _audit_log(state: GraphState) -> dict:
    """Mirrors exactly how /chat/policy, /chat/sql, /chat/actions each
    derive tool_name/action_status/records_accessed today, so the
    observability dashboard behaves identically regardless of which
    endpoint a request came through."""
    result = state["agent_result"]
    intent = state["intent"]

    usage = audit.pop_llm_usage(result)
    refusal_reason = audit.pop_refusal_reason(result)
    router_usage = state.get("router_usage") or []
    if router_usage:
        usage["input_tokens"] = (usage.get("input_tokens") or 0) + sum(u["input_tokens"] for u in router_usage)
        usage["output_tokens"] = (usage.get("output_tokens") or 0) + sum(u["output_tokens"] for u in router_usage)
        usage["llm_call_count"] = (usage.get("llm_call_count") or 0) + len(router_usage)

    records_accessed = None
    if intent == "POLICY_QA":
        tool_name = "policy_rag"
        action_status = "SUCCESS" if result.get("sources") else "NO_ANSWER"
    elif intent == "SQL_QUERY":
        tool_name = "sql_agent"
        action_status = "SUCCESS" if result.get("sql") else "REFUSED"
        records_accessed = [r.get("id") for r in result.get("rows", []) if isinstance(r, dict) and "id" in r]
    elif intent == "HR_ACTION":
        tool_name = result.get("tool_called")
        action_status = result.get("action_status")
    else:
        tool_name = None
        action_status = "NOT_APPLICABLE"

    duration_ms = round((time.perf_counter() - state["started_at"]) * 1000, 1)
    await audit.write_audit_log(
        state["db"],
        user_id=state["user_id"],
        role=state["role"],
        message=state["message"],
        intent=intent,
        tool_name=tool_name,
        action_status=action_status,
        records_accessed=records_accessed,
        latency_ms=duration_ms,
        refusal_reason=refusal_reason,
        **usage,
    )
    return {}


def _build_graph():
    builder = StateGraph(GraphState)
    builder.add_node("load_user_context", _load_user_context)
    builder.add_node("classify_intent", _classify_intent)
    builder.add_node("policy_rag_node", _policy_rag_node)
    builder.add_node("sql_agent_node", _sql_agent_node)
    builder.add_node("hr_action_node", _hr_action_node)
    builder.add_node("unhandled_node", _unhandled_node)
    builder.add_node("permission_check", _permission_check)
    builder.add_node("generate_final_response", _generate_final_response)
    builder.add_node("audit_log", _audit_log)

    builder.add_edge(START, "load_user_context")
    builder.add_edge("load_user_context", "classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        _route,
        {
            "policy_rag_node": "policy_rag_node",
            "sql_agent_node": "sql_agent_node",
            "hr_action_node": "hr_action_node",
            "unhandled_node": "unhandled_node",
        },
    )
    for node in ("policy_rag_node", "sql_agent_node", "hr_action_node", "unhandled_node"):
        builder.add_edge(node, "permission_check")
    builder.add_edge("permission_check", "generate_final_response")
    builder.add_edge("generate_final_response", "audit_log")
    builder.add_edge("audit_log", END)

    return builder.compile()


_compiled_graph = _build_graph()


async def run_graph(
    db: AsyncSession,
    message: str,
    pending_action: dict | None,
    user_id: int,
    role: str,
    access_token: str,
) -> dict:
    """Runs the full graph for one request and returns the final response
    envelope (already audit-logged). `role` is the caller's JWT-derived
    role, used as a fallback if load_user_context's DB re-fetch is ever
    unable to find the employee."""
    initial_state: GraphState = {
        "message": message,
        "pending_action": pending_action,
        "user_id": user_id,
        "role": role,
        "access_token": access_token,
        "db": db,
        "started_at": time.perf_counter(),
    }
    final_state = await _compiled_graph.ainvoke(initial_state)
    return final_state["final_response"]
