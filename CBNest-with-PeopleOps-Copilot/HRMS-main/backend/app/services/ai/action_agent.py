"""
HR Task Automation Agent.

Flow:
  message (+ optional pending_action for confirmation replies)
    -> if pending_action present: interpret yes/no, execute or cancel
    -> else: extract (tool_name, arguments) via Claude structured output
    -> permission check (services/ai/permissions.py)
    -> if high-impact tool: return requires_confirmation instead of executing
    -> else: call the backend API tool (api_tools.py) using the user's own JWT
    -> summarize the API result for the user

The agent NEVER writes to the database itself — see api_tools.py docstring.
Read-only lookups (own projects, skill search) are delegated to the SQL
Agent rather than a bespoke endpoint, since the real HRMS restricts
GET /employees/{id}/projects to ADMIN/MANAGER and there's no dedicated
skill-search endpoint at all — this is exactly the gap the SQL Agent fills.
"""
import asyncio
from datetime import date

import structlog

from app.models.enums import Role
from app.services.ai import api_tools, llm_client
from app.services.ai.permissions import HIGH_IMPACT_TOOLS, TOOL_PERMISSIONS, is_tool_permitted, permission_denied_message

logger = structlog.get_logger("ai.action_agent")

TOOL_CATALOG = """Available tools (name -> when to use -> required arguments):

- create_leave_request -> user wants to apply for leave -> {leave_type: CASUAL|SICK|EARNED, start_date: YYYY-MM-DD, end_date: YYYY-MM-DD, reason: string, is_half_day: bool, half_day_period: FIRST_HALF|SECOND_HALF|null}
- check_leave_balance -> user asks about their own remaining leave -> {}
- check_my_leave_requests -> user asks about the status of their own leave requests -> {}
- create_ticket -> user wants to raise/log an IT/HR/Onboarding issue -> {title: string, description: string, category: IT|HR|ONBOARDING, priority: LOW|MEDIUM|HIGH}
- check_ticket_status -> user asks about status of their own/assigned tickets -> {}
- view_own_projects -> user asks what projects they are on -> {}
- search_employees_by_skill -> user wants to find employees with a given skill -> {skill: string}
- approve_leave_request -> user (manager/admin) wants to approve a SPECIFIC leave request -> {request_id: int}
- reject_leave_request -> user (manager/admin) wants to reject a SPECIFIC leave request -> {request_id: int}
- update_ticket_status -> user wants to change a ticket's status -> {ticket_id: int, status: OPEN|IN_PROGRESS|RESOLVED}
- assign_ticket -> user (manager/admin) wants to assign a ticket to someone -> {ticket_id: int, assignee_id: int}
- create_announcement -> user (manager/admin) wants to post an announcement -> {title: string, body: string}
- assign_employee_to_project -> user (manager/admin) wants to staff someone on a project -> {employee_id: int, project_id: int, role_on_project: string|null}

If the message is not an HR action request at all (e.g. a policy question or a
data lookup), return tool_name "NONE".
"""

def _build_intent_system_prompt(today: str, role: str) -> str:
    return f"""You are the NovaWorks PeopleOps HR Action Agent's intent extractor.
Given the user's message, decide which single tool (if any) to call and extract its arguments.

{TOOL_CATALOG}

Today's date is {today}. Resolve relative dates ("tomorrow", "next Monday") into absolute YYYY-MM-DD dates.
The current user's role is {role}.

Return ONLY JSON: {{"tool_name": "<tool name or NONE>", "arguments": {{...}}, "confirmation_summary": "<one plain-English sentence describing exactly what this action will do, for a confirmation prompt>"}}
"""


def _extract_intent(message: str, role: str, usage_sink: list[dict] | None = None) -> dict:
    system_prompt = _build_intent_system_prompt(date.today().isoformat(), role)
    return llm_client.complete_json(system_prompt, f"User message: {message}", max_tokens=500, usage_sink=usage_sink)


async def _run_readonly_lookup(tool_name: str, arguments: dict, user_id: int, role: str) -> dict:
    """view_own_projects / search_employees_by_skill go through the SQL
    agent's safe, role-scoped query path rather than a bespoke endpoint."""
    from app.services.ai.sql_agent import generate_and_run_sql
    from app.db.session import SessionLocal

    async with SessionLocal() as db:
        if tool_name == "view_own_projects":
            question = "Which projects am I currently assigned to, and what is my role on each?"
        else:
            skill = arguments.get("skill", "")
            question = f"Which employees have the skill '{skill}'? Show their name and department."
        result = await generate_and_run_sql(db, question, user_id, role)
        return {"status_code": 200, "body": result}


async def _execute_tool(tool_name: str, arguments: dict, user_id: int, role: str, access_token: str) -> dict:
    if tool_name == "create_leave_request":
        return await api_tools.create_leave_request(arguments, access_token)
    if tool_name == "check_leave_balance":
        return await api_tools.check_leave_balance(access_token)
    if tool_name == "check_my_leave_requests":
        return await api_tools.check_my_leave_requests(access_token)
    if tool_name == "create_ticket":
        return await api_tools.create_ticket(arguments, access_token)
    if tool_name == "check_ticket_status":
        return await api_tools.check_my_tickets(access_token)
    if tool_name in ("view_own_projects", "search_employees_by_skill"):
        return await _run_readonly_lookup(tool_name, arguments, user_id, role)
    if tool_name == "approve_leave_request":
        return await api_tools.approve_leave_request(arguments["request_id"], access_token)
    if tool_name == "reject_leave_request":
        return await api_tools.reject_leave_request(arguments["request_id"], access_token)
    if tool_name == "update_ticket_status":
        return await api_tools.update_ticket_status(arguments["ticket_id"], arguments["status"], access_token)
    if tool_name == "assign_ticket":
        return await api_tools.assign_ticket(arguments["ticket_id"], arguments["assignee_id"], access_token)
    if tool_name == "create_announcement":
        return await api_tools.create_announcement(arguments, access_token)
    if tool_name == "assign_employee_to_project":
        employee_id = arguments.pop("employee_id")
        return await api_tools.assign_employee_to_project(employee_id, arguments, access_token)
    return {"status_code": 400, "body": {"detail": f"Unknown tool {tool_name}"}}


def _summarize_result(
    tool_name: str, arguments: dict, api_result: dict, usage_sink: list[dict] | None = None
) -> tuple[str, str]:
    status_code = api_result.get("status_code", 500)
    body = api_result.get("body", {})

    if 200 <= status_code < 300:
        try:
            prompt = (
                f"Tool called: {tool_name}\nArguments: {arguments}\nAPI response: {body}\n\n"
                "Write a short (1-3 sentence) confirmation message for the employee, summarizing what happened. "
                "Do not mention internal tool/API names."
            )
            text = llm_client.complete(
                "You summarize HR action results for a chat UI in a friendly, concise tone.",
                prompt,
                max_tokens=200,
                usage_sink=usage_sink,
            )
        except Exception:
            text = "Your request was completed successfully."
        return text, "SUCCESS"

    detail = "The request could not be completed."
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            detail = err.get("message", detail)
        else:
            detail = body.get("detail", detail)
    return f"I couldn't complete that: {detail}", "ERROR"


def _absorb_nested_usage(usage_sink: list[dict], api_result: dict) -> None:
    """view_own_projects / search_employees_by_skill delegate to the SQL
    Agent (see _run_readonly_lookup), which makes its own LLM call(s) and
    reports its own _llm_usage on the result body. Fold that into this
    request's usage_sink so the audit row reflects the true total cost."""
    body = api_result.get("body")
    if not isinstance(body, dict):
        return
    nested = body.pop("_llm_usage", None)
    if not nested:
        return
    usage_sink.append(
        {
            "input_tokens": nested.get("input_tokens") or 0,
            "output_tokens": nested.get("output_tokens") or 0,
            "duration_ms": nested.get("llm_duration_ms") or 0,
        }
    )


async def handle_action_request(
    message: str,
    pending_action: dict | None,
    user_id: int,
    role: str,
    access_token: str,
) -> dict:
    """Returns a dict matching ActionChatData."""
    usage_sink: list[dict] = []

    # --- Confirmation reply path ---
    if pending_action:
        affirmative = any(w in message.lower() for w in ["yes", "confirm", "go ahead", "approve it", "do it"])
        negative = any(w in message.lower() for w in ["no", "cancel", "stop", "don't", "do not"])
        if negative and not affirmative:
            return {"answer": "Okay, I've cancelled that action.", "tool_called": None, "action_status": "CANCELLED"}
        if not affirmative:
            return {
                "answer": "I didn't catch a clear yes/no — please confirm or cancel the pending action.",
                "tool_called": pending_action.get("tool_name"),
                "action_status": "AWAITING_CONFIRMATION",
                "requires_confirmation": True,
                "pending_action": pending_action,
            }
        tool_name = pending_action["tool_name"]
        arguments = pending_action.get("arguments", {})
        if not is_tool_permitted(tool_name, role):
            logger.warning("action_agent_permission_denied", role=role, user_id=user_id, tool_name=tool_name, stage="confirmation")
            return {
                "answer": permission_denied_message(tool_name),
                "tool_called": tool_name,
                "action_status": "REFUSED",
                "_refusal_reason": "PERMISSION_DENIED",
            }
        api_result = await _execute_tool(tool_name, arguments, user_id, role, access_token)
        _absorb_nested_usage(usage_sink, api_result)
        answer, status_ = _summarize_result(tool_name, arguments, api_result, usage_sink)
        logger.info("action_agent_executed", role=role, user_id=user_id, tool_name=tool_name, action_status=status_)
        return {
            "answer": answer,
            "tool_called": tool_name,
            "action_status": status_,
            "result": api_result.get("body"),
            "_llm_usage": llm_client.summarize_usage(usage_sink),
        }

    # --- Fresh request path ---
    try:
        intent = await asyncio.to_thread(_extract_intent, message, role, usage_sink)
    except Exception as exc:
        logger.warning("action_agent_intent_extraction_failed", role=role, user_id=user_id, error_type=type(exc).__name__)
        return {
            "answer": "I couldn't understand that as an HR action. Could you rephrase it?",
            "tool_called": None,
            "action_status": "ERROR",
            "_llm_usage": llm_client.summarize_usage(usage_sink),
            "_refusal_reason": "INTENT_EXTRACTION_FAILED",
        }

    tool_name = intent.get("tool_name", "NONE")
    arguments = intent.get("arguments", {}) or {}
    confirmation_summary = intent.get("confirmation_summary", "")

    if tool_name == "NONE" or tool_name not in TOOL_PERMISSIONS:
        logger.info("action_agent_not_applicable", role=role, user_id=user_id, requested_tool=tool_name)
        return {
            "answer": "I'm not able to perform that as an HR action. Try asking a policy question or a data question instead.",
            "tool_called": None,
            "action_status": "NOT_APPLICABLE",
            "_llm_usage": llm_client.summarize_usage(usage_sink),
        }

    # Permission check happens BEFORE anything else — including before we
    # show a confirmation prompt, so we never preview an unauthorized action.
    if not is_tool_permitted(tool_name, role):
        logger.warning("action_agent_permission_denied", role=role, user_id=user_id, tool_name=tool_name, stage="initial")
        return {
            "answer": permission_denied_message(tool_name),
            "tool_called": tool_name,
            "action_status": "REFUSED",
            "_llm_usage": llm_client.summarize_usage(usage_sink),
            "_refusal_reason": "PERMISSION_DENIED",
        }

    if tool_name in HIGH_IMPACT_TOOLS:
        logger.info("action_agent_awaiting_confirmation", role=role, user_id=user_id, tool_name=tool_name)
        return {
            "answer": confirmation_summary or f"Confirm you want me to run '{tool_name}'?",
            "tool_called": tool_name,
            "action_status": "AWAITING_CONFIRMATION",
            "requires_confirmation": True,
            "pending_action": {"tool_name": tool_name, "arguments": arguments},
            "_llm_usage": llm_client.summarize_usage(usage_sink),
        }

    api_result = await _execute_tool(tool_name, arguments, user_id, role, access_token)
    _absorb_nested_usage(usage_sink, api_result)
    answer, status_ = _summarize_result(tool_name, arguments, api_result, usage_sink)
    logger.info("action_agent_executed", role=role, user_id=user_id, tool_name=tool_name, action_status=status_)
    return {
        "answer": answer,
        "tool_called": tool_name,
        "action_status": status_,
        "result": api_result.get("body"),
        "_llm_usage": llm_client.summarize_usage(usage_sink),
    }
