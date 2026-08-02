import json

from app.core.config import settings
from app.services.ai import sql_agent


def _intent_rule(fake_llm, sql):
    fake_llm.when(
        lambda system, user: user.startswith("Question:"),
        json.dumps({"sql": sql, "explanation": "test"}),
    )


def _summary_rule(fake_llm, text="Here are the results."):
    fake_llm.when(lambda system, user: "Query returned" in user, text)


async def test_catalog_query_executes_and_returns_rows(db_session, fake_llm):
    _intent_rule(fake_llm, "SELECT id, name, status FROM projects WHERE status = 'ONGOING' LIMIT 100")
    _summary_rule(fake_llm)

    result = await sql_agent.generate_and_run_sql(db_session, "Which projects are ongoing?", user_id=1, role="ADMIN")

    assert result["sql"].upper().startswith("SELECT")
    assert isinstance(result["rows"], list)
    assert result["answer"]


async def test_forbidden_column_blocked_before_execution(db_session, fake_llm):
    _intent_rule(fake_llm, "SELECT id, name, current_salary_usd FROM employees")

    result = await sql_agent.generate_and_run_sql(db_session, "What is Rahul's salary?", user_id=1, role="EMPLOYEE")

    assert result["sql"] is None
    assert result["rows"] == []
    assert "can't run" in result["answer"].lower()


async def test_drop_table_blocked_before_execution(db_session, fake_llm):
    _intent_rule(fake_llm, "DROP TABLE employees;")

    result = await sql_agent.generate_and_run_sql(db_session, "Delete the employees table", user_id=1, role="ADMIN")

    assert result["sql"] is None
    assert result["rows"] == []


async def test_employee_cannot_query_another_employees_leave(db_session, fake_llm):
    # Simulates the LLM misbehaving and generating a query scoped to someone
    # else's records; the heuristic role-scope check must catch this even
    # though the system prompt already told it not to.
    _intent_rule(fake_llm, "SELECT * FROM leave_requests WHERE employee_id = 99")

    result = await sql_agent.generate_and_run_sql(db_session, "Show leave requests for employee 99", user_id=3, role="EMPLOYEE")

    assert result["sql"] is None
    assert "don't have permission" in result["answer"].lower()


async def test_employee_can_query_own_leave_requests(db_session, fake_llm):
    _intent_rule(fake_llm, "SELECT * FROM leave_requests WHERE employee_id = 3 LIMIT 100")
    _summary_rule(fake_llm)

    result = await sql_agent.generate_and_run_sql(db_session, "Show my leave requests", user_id=3, role="EMPLOYEE")

    assert result["sql"] is not None
    assert all(row.get("employee_id") == 3 for row in result["rows"])


async def test_manager_team_scoped_query_allowed(db_session, fake_llm):
    _intent_rule(
        fake_llm,
        "SELECT * FROM leave_requests WHERE employee_id IN (SELECT id FROM employees WHERE manager_id = 2)",
    )
    _summary_rule(fake_llm)

    result = await sql_agent.generate_and_run_sql(db_session, "Show my team's leave requests", user_id=2, role="MANAGER")

    assert result["sql"] is not None


async def test_agent_disabled_returns_message_without_calling_llm(db_session, fake_llm, monkeypatch):
    monkeypatch.setattr(settings, "sql_agent_enabled", False)

    result = await sql_agent.generate_and_run_sql(db_session, "Anything", user_id=1, role="ADMIN")

    assert "disabled" in result["answer"].lower()
    assert not fake_llm.calls


async def test_execution_error_handled_gracefully(db_session, fake_llm):
    _intent_rule(fake_llm, "SELECT nonexistent_column FROM projects")

    result = await sql_agent.generate_and_run_sql(db_session, "Broken query", user_id=1, role="ADMIN")

    assert result["sql"] is None
    assert "issue executing" in result["answer"].lower()


async def test_malformed_llm_json_handled_gracefully(db_session, fake_llm):
    fake_llm.when(lambda system, user: user.startswith("Question:"), "not valid json at all")

    result = await sql_agent.generate_and_run_sql(db_session, "Anything", user_id=1, role="ADMIN")

    assert result["sql"] is None
    assert result["rows"] == []
