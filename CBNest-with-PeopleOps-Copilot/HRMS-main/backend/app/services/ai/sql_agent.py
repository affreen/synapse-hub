"""
SQL Agent for HR Intelligence.

Flow: build a schema description (allow-listed tables/columns only) ->
ask Claude to generate ONE read-only SELECT -> validate with
sql_guardrails.validate_sql -> apply a role-scoping heuristic check ->
execute against the app's own SQLite DB (async, via `text()`) with a hard
row cap -> strip any forbidden fields defensively -> summarize in natural
language.

KNOWN LIMITATION (see docs/ai_architecture.md): MANAGER-level team scoping
is a heuristic regex check, not a formally verified query rewrite. A
production version should use parameterized query templates or a
server-side query-rewriting layer instead of trusting the LLM's own scoping.
"""
import asyncio
import re

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.enums import Role
from app.services.ai import llm_client
from app.services.ai.sql_guardrails import validate_sql, strip_forbidden_fields

logger = structlog.get_logger("ai.sql_agent")

SCHEMA_DESCRIPTION = """
TABLES (read-only, only these are queryable):

employees(id, name, email, role, status, department_id, manager_id, joining_date, phone, address, blood_type, occupancy)
  -- role is one of: ADMIN, MANAGER, EMPLOYEE. status is one of: ACTIVE, INACTIVE.
  -- NOTE: hashed_password, date_of_birth, profile_photo_path, profile_photo_mime, current_salary_usd,
  --       bank_name, bank_account_number, bank_account_name, bank_branch, bank_ifsc,
  --       pan_number, pan_name, pan_dob, pf_uan, esi_no are NEVER selectable.

departments(id, name, location)

projects(id, name, description, status)
  -- status is one of: ONGOING, COMPLETED, ON_HOLD, PLANNED

employee_projects(id, employee_id, project_id, role_on_project)

skills(id, name, normalized_name)

employee_skills(id, employee_id, skill_id, level)
  -- level is one of: BEGINNER, INTERMEDIATE, EXPERT

job_history(id, employee_id, designation, business_unit, department, start_date, end_date, is_current)

leave_balances(id, employee_id, leave_type, total, used, remaining)
  -- leave_type is one of: CASUAL, SICK, EARNED

leave_requests(id, employee_id, leave_type, start_date, end_date, reason, is_half_day, half_day_period, status, approver_id)
  -- status is one of: PENDING, APPROVED, REJECTED

tickets(id, employee_id, assignee_id, title, description, category, priority, status, created_at)
  -- category: IT, HR, ONBOARDING. priority: LOW, MEDIUM, HIGH. status: OPEN, IN_PROGRESS, RESOLVED.
"""

SQL_SYSTEM_PROMPT_TEMPLATE = """You are the NovaWorks PeopleOps SQL Agent. You write a SINGLE, READ-ONLY
SQLite SELECT statement that answers the user's question, using ONLY the schema below.

{schema}

STRICT RULES:
- Output ONLY valid SQLite SQL. No INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/PRAGMA — SELECT (or WITH ... SELECT) only.
- Never select hashed_password, date_of_birth, profile_photo_path, profile_photo_mime, current_salary_usd,
  bank_name, bank_account_number, bank_account_name, bank_branch, bank_ifsc, pan_number, pan_name, pan_dob,
  pf_uan, esi_no.
- Never write more than one statement. Never use comments.
- Always add a reasonable LIMIT (<= {max_rows}) unless the question clearly wants a single aggregate value.

ROLE-BASED SCOPING (the current user's identity is fixed):
Current user: id={user_id}, role={role}
{scope_rules}

Return ONLY JSON: {{"sql": "<the SELECT statement>", "explanation": "<one sentence, for internal logging only>"}}
"""

SCOPE_RULES = {
    Role.EMPLOYEE: (
        "- For leave_requests, leave_balances, tickets, job_history: filter to this user's own records only "
        "(employee_id = {user_id}).\n"
        "- You MAY query employees/departments/projects/skills/employee_skills/employee_projects broadly for "
        "catalog-style lookups (e.g. 'who knows Python', 'which projects are ongoing') but must not join those "
        "results to another employee's leave_requests, leave_balances, or tickets.\n"
    ),
    Role.MANAGER: (
        "- For your OWN leave_requests/leave_balances/tickets: filter employee_id = {user_id}.\n"
        "- For team-level leave/ticket data: filter using employees.manager_id = {user_id} via a join or subquery "
        "(e.g. employee_id IN (SELECT id FROM employees WHERE manager_id = {user_id})). Do not return leave or "
        "ticket data for employees outside your reporting line.\n"
        "- Catalog data (projects, skills, departments) can be queried broadly.\n"
    ),
    Role.ADMIN: (
        "- Broad read access to all allow-listed tables/columns is permitted. Still never select forbidden "
        "sensitive columns listed above.\n"
    ),
}


def _build_system_prompt(user_id: int, role: str, max_rows: int) -> str:
    scope_rules = SCOPE_RULES[Role(role)].format(user_id=user_id)
    return SQL_SYSTEM_PROMPT_TEMPLATE.format(
        schema=SCHEMA_DESCRIPTION, max_rows=max_rows, user_id=user_id, role=role, scope_rules=scope_rules
    )


def _heuristic_role_scope_check(sql: str, role: str, user_id: int) -> str | None:
    sql_lower = sql.lower()
    personal_tables = ("leave_requests", "leave_balances", "tickets", "job_history")
    if not any(t in sql_lower for t in personal_tables):
        return None

    has_own_id = re.search(rf"employee_id\s*=\s*{user_id}\b", sql_lower) is not None

    if role == Role.EMPLOYEE.value:
        if not has_own_id:
            return "This query would access another employee's leave or ticket records, which you don't have permission to view."
    elif role == Role.MANAGER.value:
        has_manager_scope = "manager_id" in sql_lower
        if not (has_own_id or has_manager_scope):
            return "This query would access leave or ticket records outside your team, which you don't have permission to view."
    return None


async def generate_and_run_sql(db: AsyncSession, question: str, user_id: int, role: str) -> dict:
    """Returns {"answer": str, "sql": str|None, "rows": [...]}. Never raises
    outward — all failure paths return a graceful, non-leaking message."""
    if not settings.sql_agent_enabled:
        return {
            "answer": "The data assistant is currently disabled.",
            "sql": None,
            "rows": [],
            "_llm_usage": {},
            "_refusal_reason": "AGENT_DISABLED",
        }

    max_rows = settings.sql_agent_max_rows
    system_prompt = _build_system_prompt(user_id, role, max_rows)
    usage_sink: list[dict] = []

    try:
        result = await asyncio.to_thread(
            llm_client.complete_json, system_prompt, f"Question: {question}", 500, usage_sink
        )
        candidate_sql = result.get("sql", "")
    except Exception as exc:
        logger.warning("sql_agent_generation_failed", role=role, user_id=user_id, error_type=type(exc).__name__)
        return {
            "answer": "I couldn't turn that into a safe data query. Try rephrasing your question.",
            "sql": None,
            "rows": [],
            "_llm_usage": llm_client.summarize_usage(usage_sink),
            "_refusal_reason": "LLM_GENERATION_FAILED",
        }

    validation = validate_sql(candidate_sql, max_rows=max_rows)
    if not validation.ok:
        logger.info(
            "sql_agent_validation_blocked", role=role, user_id=user_id,
            reason=validation.reason, reason_code=validation.reason_code,
        )
        return {
            "answer": f"I can't run that query: {validation.reason}",
            "sql": None,
            "rows": [],
            "_llm_usage": llm_client.summarize_usage(usage_sink),
            "_refusal_reason": validation.reason_code or "VALIDATION_BLOCKED",
        }

    scope_error = _heuristic_role_scope_check(validation.sanitized_sql, role, user_id)
    if scope_error:
        logger.warning("sql_agent_scope_blocked", role=role, user_id=user_id, sql=validation.sanitized_sql)
        return {
            "answer": scope_error,
            "sql": None,
            "rows": [],
            "_llm_usage": llm_client.summarize_usage(usage_sink),
            "_refusal_reason": "ROLE_SCOPE_VIOLATION",
        }

    try:
        result_proxy = await db.execute(text(validation.sanitized_sql))
        columns = list(result_proxy.keys())
        raw_rows = [dict(zip(columns, row)) for row in result_proxy.fetchall()]
    except Exception as exc:
        logger.error(
            "sql_agent_execution_failed", role=role, user_id=user_id,
            error_type=type(exc).__name__, sql=validation.sanitized_sql,
        )
        return {
            "answer": "I ran into an issue executing that query. Please try rephrasing your question.",
            "sql": None,
            "rows": [],
            "_llm_usage": llm_client.summarize_usage(usage_sink),
            "_refusal_reason": "EXECUTION_ERROR",
        }

    logger.info("sql_agent_executed", role=role, user_id=user_id, row_count=len(raw_rows))
    rows = strip_forbidden_fields(raw_rows)

    if not rows:
        answer = "I didn't find any matching records for that question."
    else:
        summary_prompt = (
            f"Question: {question}\n\nQuery returned {len(rows)} row(s). Sample data (JSON): "
            f"{rows[:10]}\n\nWrite a concise 1-3 sentence natural language answer for the user. "
            f"Do not mention SQL, table names, or internal implementation details."
        )
        try:
            answer = await asyncio.to_thread(
                llm_client.complete,
                "You summarize HR data query results for an employee-facing chat UI. Be concise and factual.",
                summary_prompt,
                300,
                0.2,
                usage_sink,
            )
        except Exception:
            answer = f"Found {len(rows)} matching record(s)."

    return {
        "answer": answer,
        "sql": validation.sanitized_sql,
        "rows": rows,
        "_llm_usage": llm_client.summarize_usage(usage_sink),
    }
