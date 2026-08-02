import json
from datetime import date

from app.models.enums import Role
from app.services.ai import action_agent


def test_build_intent_system_prompt_does_not_raise_for_any_role():
    # Regression test: TOOL_CATALOG contains literal single-brace tool
    # argument examples (e.g. "{leave_type: CASUAL|SICK|EARNED, ...}").
    # Building this prompt previously crashed with `KeyError: 'leave_type'`
    # because it ran the whole string through str.format() a second time,
    # which tried to treat every brace in TOOL_CATALOG as a format field.
    for role in Role:
        prompt = action_agent._build_intent_system_prompt(date.today().isoformat(), role.value)
        assert "create_leave_request" in prompt
        assert role.value in prompt


def _intent_rule(fake_llm, tool_name, arguments=None, confirmation_summary="Do the thing."):
    fake_llm.when(
        lambda system, user: user.startswith("User message:"),
        json.dumps({"tool_name": tool_name, "arguments": arguments or {}, "confirmation_summary": confirmation_summary}),
    )


def _summary_rule(fake_llm, text="Done."):
    fake_llm.when(lambda system, user: "Tool called:" in user, text)


async def test_direct_low_impact_action_executes_immediately(fake_llm, monkeypatch):
    _intent_rule(
        fake_llm,
        "create_ticket",
        {"title": "VPN down", "description": "VPN not working", "category": "IT", "priority": "HIGH"},
    )
    _summary_rule(fake_llm, "Your ticket has been created.")

    async def fake_create_ticket(arguments, access_token):
        return {"status_code": 201, "body": {"success": True, "data": {"id": 99, **arguments}}}

    monkeypatch.setattr(action_agent.api_tools, "create_ticket", fake_create_ticket)

    result = await action_agent.handle_action_request(
        message="Create a high-priority IT ticket for VPN not working.",
        pending_action=None,
        user_id=3,
        role="EMPLOYEE",
        access_token="fake-token",
    )

    assert result["action_status"] == "SUCCESS"
    assert result["tool_called"] == "create_ticket"


async def test_high_impact_action_requires_confirmation_before_executing(fake_llm, monkeypatch):
    _intent_rule(fake_llm, "approve_leave_request", {"request_id": 1}, "This will approve leave request #1.")

    called = {"count": 0}

    async def fake_approve(request_id, access_token):
        called["count"] += 1
        return {"status_code": 200, "body": {"success": True}}

    monkeypatch.setattr(action_agent.api_tools, "approve_leave_request", fake_approve)

    result = await action_agent.handle_action_request(
        message="Approve leave request 1.",
        pending_action=None,
        user_id=2,
        role="MANAGER",
        access_token="fake-token",
    )

    assert result["action_status"] == "AWAITING_CONFIRMATION"
    assert result["requires_confirmation"] is True
    assert result["pending_action"] == {"tool_name": "approve_leave_request", "arguments": {"request_id": 1}}
    assert called["count"] == 0  # must not execute before confirmation


async def test_confirmation_yes_executes_the_pending_action(fake_llm, monkeypatch):
    _summary_rule(fake_llm, "Leave request approved.")
    called = {"count": 0}

    async def fake_approve(request_id, access_token):
        called["count"] += 1
        return {"status_code": 200, "body": {"success": True, "data": {"id": request_id, "status": "APPROVED"}}}

    monkeypatch.setattr(action_agent.api_tools, "approve_leave_request", fake_approve)

    result = await action_agent.handle_action_request(
        message="yes",
        pending_action={"tool_name": "approve_leave_request", "arguments": {"request_id": 1}},
        user_id=2,
        role="MANAGER",
        access_token="fake-token",
    )

    assert result["action_status"] == "SUCCESS"
    assert called["count"] == 1


async def test_confirmation_no_cancels_without_executing(fake_llm, monkeypatch):
    called = {"count": 0}

    async def fake_approve(request_id, access_token):
        called["count"] += 1
        return {"status_code": 200, "body": {}}

    monkeypatch.setattr(action_agent.api_tools, "approve_leave_request", fake_approve)

    result = await action_agent.handle_action_request(
        message="no, cancel that",
        pending_action={"tool_name": "approve_leave_request", "arguments": {"request_id": 1}},
        user_id=2,
        role="MANAGER",
        access_token="fake-token",
    )

    assert result["action_status"] == "CANCELLED"
    assert called["count"] == 0


async def test_disallowed_tool_for_role_is_refused_before_confirmation(fake_llm):
    # Even if the LLM returns a tool the caller's role isn't allowed to run,
    # the deterministic permission check must refuse it before any
    # confirmation prompt is shown.
    _intent_rule(fake_llm, "approve_leave_request", {"request_id": 1})

    result = await action_agent.handle_action_request(
        message="Approve leave request 1.",
        pending_action=None,
        user_id=3,
        role="EMPLOYEE",
        access_token="fake-token",
    )

    assert result["action_status"] == "REFUSED"
    assert result.get("requires_confirmation") is not True


async def test_unmatched_message_returns_not_applicable(fake_llm):
    _intent_rule(fake_llm, "NONE")

    result = await action_agent.handle_action_request(
        message="What's the weather like?",
        pending_action=None,
        user_id=3,
        role="EMPLOYEE",
        access_token="fake-token",
    )

    assert result["action_status"] == "NOT_APPLICABLE"
    assert result["tool_called"] is None


async def test_no_destructive_tool_exists_for_delete_all(fake_llm):
    _intent_rule(fake_llm, "NONE")

    result = await action_agent.handle_action_request(
        message="Delete all leave requests.",
        pending_action=None,
        user_id=1,
        role="ADMIN",
        access_token="fake-token",
    )

    assert result["action_status"] == "NOT_APPLICABLE"


async def test_llm_failure_returns_graceful_error(fake_llm):
    # No rule registered on fake_llm at all, so calling it raises
    # AssertionError - this must be caught by handle_action_request's
    # broad except around _extract_intent, not propagate as a 500.
    result = await action_agent.handle_action_request(
        message="Do something totally unmatched by any rule",
        pending_action=None,
        user_id=1,
        role="ADMIN",
        access_token="fake-token",
    )

    assert result["action_status"] == "ERROR"
