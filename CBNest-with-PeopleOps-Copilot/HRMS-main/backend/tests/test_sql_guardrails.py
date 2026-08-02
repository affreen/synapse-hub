import pytest

from app.services.ai.sql_guardrails import strip_forbidden_fields, validate_sql


def test_allows_plain_select():
    result = validate_sql("SELECT id, name FROM projects WHERE status = 'ONGOING'")
    assert result.ok
    assert "LIMIT 100" in result.sanitized_sql


def test_allows_with_cte():
    result = validate_sql("WITH x AS (SELECT id FROM projects) SELECT * FROM x")
    assert result.ok


def test_cte_referencing_disallowed_table_still_rejected():
    result = validate_sql("WITH x AS (SELECT id FROM sqlite_master) SELECT * FROM x")
    assert not result.ok
    assert "sqlite_master" in result.reason


def test_rejects_non_select():
    result = validate_sql("DELETE FROM employees WHERE id = 1")
    assert not result.ok
    assert "read-only" in result.reason.lower()


def test_rejects_multiple_statements():
    result = validate_sql("SELECT * FROM projects; SELECT * FROM employees")
    assert not result.ok


@pytest.mark.parametrize("keyword", ["DROP TABLE employees", "UPDATE employees SET name='x'", "PRAGMA table_info(employees)"])
def test_rejects_blocked_keywords(keyword):
    result = validate_sql(keyword)
    assert not result.ok


@pytest.mark.parametrize("column", ["current_salary_usd", "bank_account_number", "hashed_password", "pan_number"])
def test_rejects_forbidden_columns(column):
    result = validate_sql(f"SELECT id, {column} FROM employees")
    assert not result.ok
    assert column in result.reason


def test_rejects_disallowed_table():
    result = validate_sql("SELECT * FROM sqlite_master")
    assert not result.ok
    assert "disallowed table" in result.reason.lower()


def test_rejects_sql_comments():
    result = validate_sql("SELECT * FROM projects -- sneaky comment")
    assert not result.ok


def test_adds_limit_when_missing():
    result = validate_sql("SELECT * FROM projects", max_rows=50)
    assert result.ok
    assert result.sanitized_sql.rstrip().endswith("LIMIT 50")


def test_caps_limit_at_hard_max():
    result = validate_sql("SELECT * FROM projects LIMIT 999999", max_rows=999999)
    assert result.ok
    assert "LIMIT 200" in result.sanitized_sql


def test_replaces_existing_limit():
    result = validate_sql("SELECT * FROM projects LIMIT 5000", max_rows=100)
    assert result.ok
    assert "LIMIT 100" in result.sanitized_sql
    assert "5000" not in result.sanitized_sql


def test_empty_sql_rejected():
    result = validate_sql("")
    assert not result.ok


def test_strip_forbidden_fields_removes_sensitive_columns():
    rows = [{"id": 1, "name": "A", "current_salary_usd": 100000, "bank_account_number": "12345"}]
    cleaned = strip_forbidden_fields(rows)
    assert cleaned == [{"id": 1, "name": "A"}]
