"""
Tests for the LangGraph orchestration in services/ai/graph.py.

These test the graph's own wiring (routing, the permission_check
checkpoint, response normalization, audit field derivation) — not the
agents' internals, which already have their own coverage in
test_policy_rag.py / test_sql_agent.py / test_action_agent.py. Each agent
entry point is monkeypatched to a controlled stand-in, same layering as
those other test files use for their own external boundaries.

audit.write_audit_log performs a real DB write, so every test here
monkeypatches it to a recorder instead of letting it run — consistent with
this suite's existing rule that no test writes to the seeded dev DB (see
conftest.py's db_session docstring).
"""
from app.services.ai import graph


def _capture_audit(monkeypatch):
    calls = []

    async def fake_write_audit_log(db, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(graph.audit, "write_audit_log", fake_write_audit_log)
    return calls


def _stub_classify_intent(monkeypatch, intent, confidence=0.9):
    async def fake_classify_intent(message, usage_sink=None):
        return {"intent": intent, "confidence": confidence, "reason": "stub"}

    monkeypatch.setattr(graph.router_agent, "classify_intent", fake_classify_intent)


async def test_run_graph_routes_policy_question_to_policy_rag(monkeypatch, db_session):
    audit_calls = _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "POLICY_QA")

    async def fake_answer_policy_question(db, question):
        return {"answer": "Leave is allocated per policy.", "sources": [{"title": "Leave Policy", "category": "LEAVE", "filename": "seed_policy_01.md"}]}

    monkeypatch.setattr(graph.policy_rag, "answer_policy_question", fake_answer_policy_question)

    result = await graph.run_graph(
        db=db_session, message="What is the leave policy?", pending_action=None,
        user_id=3, role="EMPLOYEE", access_token="fake-token",
    )

    assert result["intent"] == "POLICY_QA"
    assert result["answer"] == "Leave is allocated per policy."
    assert result["sources"] == [{"title": "Leave Policy", "category": "LEAVE", "filename": "seed_policy_01.md"}]
    assert len(audit_calls) == 1
    assert audit_calls[0]["intent"] == "POLICY_QA"
    assert audit_calls[0]["tool_name"] == "policy_rag"
    assert audit_calls[0]["action_status"] == "SUCCESS"


async def test_run_graph_no_answer_policy_question_logs_no_answer(monkeypatch, db_session):
    audit_calls = _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "POLICY_QA")

    async def fake_answer_policy_question(db, question):
        return {"answer": "I don't have enough information.", "sources": []}

    monkeypatch.setattr(graph.policy_rag, "answer_policy_question", fake_answer_policy_question)

    result = await graph.run_graph(
        db=db_session, message="What is the quantum policy?", pending_action=None,
        user_id=3, role="EMPLOYEE", access_token="fake-token",
    )

    assert result["sources"] == []
    assert audit_calls[0]["action_status"] == "NO_ANSWER"


async def test_run_graph_routes_data_question_to_sql_agent(monkeypatch, db_session):
    audit_calls = _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "SQL_QUERY")

    async def fake_generate_and_run_sql(db, question, user_id, role):
        return {"answer": "1 project found.", "sql": "SELECT id FROM projects LIMIT 1", "rows": [{"id": 42}]}

    monkeypatch.setattr(graph.sql_agent, "generate_and_run_sql", fake_generate_and_run_sql)

    result = await graph.run_graph(
        db=db_session, message="Which projects are ongoing?", pending_action=None,
        user_id=3, role="EMPLOYEE", access_token="fake-token",
    )

    assert result["intent"] == "SQL_QUERY"
    assert result["rows"] == [{"id": 42}]
    assert audit_calls[0]["tool_name"] == "sql_agent"
    assert audit_calls[0]["action_status"] == "SUCCESS"
    assert audit_calls[0]["records_accessed"] == [42]


async def test_run_graph_routes_action_request_to_action_agent(monkeypatch, db_session):
    audit_calls = _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "HR_ACTION")

    async def fake_handle_action_request(message, pending_action, user_id, role, access_token):
        return {"answer": "Ticket created.", "tool_called": "create_ticket", "action_status": "SUCCESS"}

    monkeypatch.setattr(graph.action_agent, "handle_action_request", fake_handle_action_request)

    result = await graph.run_graph(
        db=db_session, message="Create a ticket for VPN issue", pending_action=None,
        user_id=3, role="EMPLOYEE", access_token="fake-token",
    )

    assert result["intent"] == "HR_ACTION"
    assert result["tool_called"] == "create_ticket"
    assert result["action_status"] == "SUCCESS"
    assert audit_calls[0]["tool_name"] == "create_ticket"
    assert audit_calls[0]["action_status"] == "SUCCESS"


async def test_run_graph_unknown_intent_returns_graceful_fallback(monkeypatch, db_session):
    audit_calls = _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "UNKNOWN", confidence=0.1)

    result = await graph.run_graph(
        db=db_session, message="asdkjfh nonsense", pending_action=None,
        user_id=3, role="EMPLOYEE", access_token="fake-token",
    )

    assert "not sure how to help" in result["answer"].lower()
    assert audit_calls[0]["action_status"] == "NOT_APPLICABLE"
    assert audit_calls[0]["tool_name"] is None


async def test_run_graph_pending_action_skips_classification(monkeypatch, db_session):
    _capture_audit(monkeypatch)

    async def fail_if_called(message, usage_sink=None):
        raise AssertionError("classify_intent should never be called for a pending_action reply")

    monkeypatch.setattr(graph.router_agent, "classify_intent", fail_if_called)

    seen = {}

    async def fake_handle_action_request(message, pending_action, user_id, role, access_token):
        seen["pending_action"] = pending_action
        seen["message"] = message
        return {"answer": "Approved.", "tool_called": "approve_leave_request", "action_status": "SUCCESS"}

    monkeypatch.setattr(graph.action_agent, "handle_action_request", fake_handle_action_request)

    pending = {"tool_name": "approve_leave_request", "arguments": {"request_id": 1}}
    result = await graph.run_graph(
        db=db_session, message="yes", pending_action=pending,
        user_id=2, role="MANAGER", access_token="fake-token",
    )

    assert result["intent"] == "HR_ACTION"
    assert seen["pending_action"] == pending


async def test_run_graph_permission_check_catches_unpermitted_tool(monkeypatch, db_session):
    """The standout case: even if the HR Action Agent had a bug and
    returned a tool_called + SUCCESS for a tool this role isn't permitted
    to use, the graph's permission_check node must still catch it and
    downgrade the result to a refusal — proving the checkpoint is a real
    second line of defense, not just decorative."""
    audit_calls = _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "HR_ACTION")

    async def buggy_handle_action_request(message, pending_action, user_id, role, access_token):
        # approve_leave_request requires MANAGER — this simulates the agent
        # incorrectly letting an EMPLOYEE through.
        return {"answer": "Approved.", "tool_called": "approve_leave_request", "action_status": "SUCCESS"}

    monkeypatch.setattr(graph.action_agent, "handle_action_request", buggy_handle_action_request)

    result = await graph.run_graph(
        db=db_session, message="Approve leave request id 1", pending_action=None,
        user_id=3, role="EMPLOYEE", access_token="fake-token",
    )

    assert result["action_status"] == "REFUSED"
    assert "do not have permission" in result["answer"].lower()
    assert audit_calls[0]["action_status"] == "REFUSED"
    assert audit_calls[0]["refusal_reason"] == "PERMISSION_DENIED"


async def test_load_user_context_uses_fresh_db_role_not_stale_caller_role(monkeypatch, db_session):
    """Employee #3 is seeded as EMPLOYEE. Even if the caller passes a stale
    JWT-derived role of ADMIN (e.g. token issued before a demotion), the
    graph must re-fetch and use the real current role from the DB for
    downstream permission/scope decisions — not the caller-supplied value."""
    _capture_audit(monkeypatch)
    _stub_classify_intent(monkeypatch, "SQL_QUERY")

    seen_role = {}

    async def fake_generate_and_run_sql(db, question, user_id, role):
        seen_role["role"] = role
        return {"answer": "ok", "sql": "SELECT 1", "rows": []}

    monkeypatch.setattr(graph.sql_agent, "generate_and_run_sql", fake_generate_and_run_sql)

    await graph.run_graph(
        db=db_session, message="Show my project assignments", pending_action=None,
        user_id=3, role="ADMIN", access_token="fake-token",
    )

    assert seen_role["role"] == "EMPLOYEE"
