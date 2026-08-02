"""
AI Permissions Matrix (code form of docs/ai_permissions_matrix.md), imported
by both the SQL agent's role-scope check and the Action Agent's tool
permission check so the matrix in the docs, this module, and actual
enforced behavior never drift apart.
"""
from dataclasses import dataclass

from app.models.enums import Role

ROLE_RANK = {Role.EMPLOYEE: 0, Role.MANAGER: 1, Role.ADMIN: 2}


def role_at_least(role: Role, minimum: Role) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


@dataclass(frozen=True)
class ToolPermission:
    tool_name: str
    minimum_role: Role
    description: str


TOOL_PERMISSIONS: dict[str, ToolPermission] = {
    "create_leave_request": ToolPermission("create_leave_request", Role.EMPLOYEE, "Apply for own leave"),
    "check_leave_balance": ToolPermission("check_leave_balance", Role.EMPLOYEE, "Check own leave balance"),
    "check_my_leave_requests": ToolPermission("check_my_leave_requests", Role.EMPLOYEE, "Check own leave request status"),
    "create_ticket": ToolPermission("create_ticket", Role.EMPLOYEE, "Raise a support ticket"),
    "check_ticket_status": ToolPermission("check_ticket_status", Role.EMPLOYEE, "Check own ticket status"),
    "view_own_projects": ToolPermission("view_own_projects", Role.EMPLOYEE, "View own project assignments"),
    "search_employees_by_skill": ToolPermission("search_employees_by_skill", Role.EMPLOYEE, "Search employees by skill (limited fields)"),
    "approve_leave_request": ToolPermission("approve_leave_request", Role.MANAGER, "Approve a leave request"),
    "reject_leave_request": ToolPermission("reject_leave_request", Role.MANAGER, "Reject a leave request"),
    "update_ticket_status": ToolPermission("update_ticket_status", Role.EMPLOYEE, "Update a ticket's status (own/assigned, or any if manager/admin)"),
    "assign_ticket": ToolPermission("assign_ticket", Role.MANAGER, "Assign a ticket to someone"),
    "create_announcement": ToolPermission("create_announcement", Role.MANAGER, "Post an announcement"),
    "assign_employee_to_project": ToolPermission("assign_employee_to_project", Role.MANAGER, "Assign an employee to a project"),
}

# High-impact actions that require an explicit confirmation step before the
# tool is actually executed (Bonus #2: Human-in-the-Loop).
HIGH_IMPACT_TOOLS = {
    "approve_leave_request",
    "reject_leave_request",
    "create_announcement",
    "assign_employee_to_project",
    "assign_ticket",
}


def is_tool_permitted(tool_name: str, role: str) -> bool:
    perm = TOOL_PERMISSIONS.get(tool_name)
    if not perm:
        return False
    return role_at_least(Role(role), perm.minimum_role)


def permission_denied_message(tool_name: str) -> str:
    """Deliberately generic — never confirms/denies whether the underlying
    record exists (see assignment's 'good vs bad refusal' example)."""
    return "You do not have permission to perform that action."
