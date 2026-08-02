"""
Guardrails for the read-only NL -> SQL agent. This is the enforcement
point for the assignment's "Critical Architecture Rule": agents never run
arbitrary SQL. Every LLM-generated query passes through `validate_sql`
before touching the DB. If validation fails, nothing is executed.
"""
import re
from dataclasses import dataclass

import sqlparse

# Columns that must never appear in AI-generated SQL or AI responses,
# regardless of role — matches app/models/employee.py exactly, plus a few
# extra sensitive finance fields present in this schema (bank_name, pf_uan, esi_no).
FORBIDDEN_COLUMNS = {
    "hashed_password",
    "date_of_birth",
    "profile_photo_path",
    "profile_photo_mime",
    "current_salary_usd",
    "bank_name",
    "bank_account_number",
    "bank_account_name",
    "bank_branch",
    "bank_ifsc",
    "pan_number",
    "pan_name",
    "pan_dob",
    "pf_uan",
    "esi_no",
}

# Tables the SQL agent is allowed to touch, per the assignment's
# "Recommended Tables" list, mapped onto this repo's real table names.
ALLOWED_TABLES = {
    "employees",
    "departments",
    "projects",
    "employee_projects",
    "skills",
    "employee_skills",
    "job_history",
    "leave_balances",
    "leave_requests",
    "tickets",
}

BLOCKED_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "pragma", "attach", "detach", "grant", "revoke", "vacuum",
    "exec", "execute",
}

MAX_ROWS_HARD_CAP = 200


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    sanitized_sql: str = ""
    # Stable machine-readable code for the rejection (vs. `reason`'s free
    # text, which embeds dynamic values like column/table names and can't
    # be grouped cleanly for observability aggregation).
    reason_code: str = ""


def _contains_forbidden_column(sql_lower: str) -> str | None:
    for col in FORBIDDEN_COLUMNS:
        if re.search(rf"\b{re.escape(col)}\b", sql_lower):
            return col
    return None


def _contains_blocked_keyword(sql_lower: str) -> str | None:
    token_set = set(re.findall(r"[a-z_]+", sql_lower))
    for kw in BLOCKED_KEYWORDS:
        if kw in token_set:
            return kw
    return None


def _referenced_tables(parsed_statement) -> set[str]:
    tables = set()
    tokens = [t for t in parsed_statement.flatten() if not t.is_whitespace]
    for i, tok in enumerate(tokens):
        val = tok.value.lower()
        if val in ("from", "join") and i + 1 < len(tokens):
            nxt = tokens[i + 1].value.strip('`"[]').lower()
            if nxt:
                tables.add(nxt)
    return tables


def _cte_names(sql: str) -> set[str]:
    """Names a WITH clause defines (e.g. `WITH x AS (...)`) aren't real
    tables, so a query referencing them via `FROM x` shouldn't be rejected
    as touching a disallowed table."""
    if not sql.strip().lower().startswith("with"):
        return set()
    return {name.lower() for name in re.findall(r"\b(\w+)\s+as\s*\(", sql, flags=re.IGNORECASE)}


def validate_sql(sql: str, max_rows: int = 100) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(ok=False, reason="Empty SQL generated.", reason_code="EMPTY_SQL")

    sql_lower = sql.strip().lower()

    if not sql_lower.startswith("select") and not sql_lower.startswith("with"):
        return ValidationResult(
            ok=False, reason="Only read-only SELECT queries are allowed.", reason_code="NOT_SELECT"
        )

    statements = [s for s in sqlparse.split(sql) if s.strip()]
    if len(statements) != 1:
        return ValidationResult(
            ok=False, reason="Only a single SQL statement is allowed per request.", reason_code="MULTIPLE_STATEMENTS"
        )

    blocked = _contains_blocked_keyword(sql_lower)
    if blocked:
        return ValidationResult(
            ok=False, reason=f"Query contains a blocked operation: {blocked.upper()}.", reason_code="BLOCKED_KEYWORD"
        )

    forbidden_col = _contains_forbidden_column(sql_lower)
    if forbidden_col:
        return ValidationResult(
            ok=False,
            reason=f"Query references a restricted field ({forbidden_col}) that the AI cannot expose.",
            reason_code="FORBIDDEN_COLUMN",
        )

    if "--" in sql or "/*" in sql or sql.count(";") > 1:
        return ValidationResult(
            ok=False,
            reason="Query contains disallowed syntax (comments or multiple statements).",
            reason_code="DISALLOWED_SYNTAX",
        )

    parsed = sqlparse.parse(sql)[0]
    tables = _referenced_tables(parsed) - _cte_names(sql)
    unknown_tables = tables - ALLOWED_TABLES
    if unknown_tables:
        return ValidationResult(
            ok=False,
            reason=f"Query references disallowed table(s): {', '.join(unknown_tables)}.",
            reason_code="DISALLOWED_TABLE",
        )

    effective_limit = min(max_rows, MAX_ROWS_HARD_CAP)
    cleaned = sql.strip().rstrip(";")
    if re.search(r"\blimit\s+\d+", cleaned, flags=re.IGNORECASE):
        cleaned = re.sub(r"\blimit\s+\d+", f"LIMIT {effective_limit}", cleaned, flags=re.IGNORECASE)
    else:
        cleaned = f"{cleaned} LIMIT {effective_limit}"

    return ValidationResult(ok=True, sanitized_sql=cleaned)


def strip_forbidden_fields(rows: list[dict]) -> list[dict]:
    """Defense in depth: strip any forbidden column that made it into a
    result set (e.g. via `select *`) before it reaches the model or client."""
    return [{k: v for k, v in row.items() if k not in FORBIDDEN_COLUMNS} for row in rows]
