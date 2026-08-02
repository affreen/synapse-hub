import pytest

from app.services.ai.permissions import (
    HIGH_IMPACT_TOOLS,
    TOOL_PERMISSIONS,
    is_tool_permitted,
    permission_denied_message,
)


def test_unknown_tool_is_never_permitted():
    assert is_tool_permitted("delete_all_leave_requests", "ADMIN") is False


@pytest.mark.parametrize(
    "tool_name,role,expected",
    [
        ("create_leave_request", "EMPLOYEE", True),
        ("create_leave_request", "MANAGER", True),
        ("create_leave_request", "ADMIN", True),
        ("approve_leave_request", "EMPLOYEE", False),
        ("approve_leave_request", "MANAGER", True),
        ("approve_leave_request", "ADMIN", True),
        ("reject_leave_request", "EMPLOYEE", False),
        ("create_announcement", "EMPLOYEE", False),
        ("create_announcement", "MANAGER", True),
        ("assign_employee_to_project", "EMPLOYEE", False),
        ("assign_employee_to_project", "MANAGER", True),
        ("assign_ticket", "EMPLOYEE", False),
        ("assign_ticket", "ADMIN", True),
    ],
)
def test_role_permission_matrix(tool_name, role, expected):
    assert is_tool_permitted(tool_name, role) is expected


def test_every_registered_tool_has_a_high_impact_classification():
    # every HIGH_IMPACT_TOOLS entry must be a real, registered tool
    assert HIGH_IMPACT_TOOLS.issubset(TOOL_PERMISSIONS.keys())


def test_permission_denied_message_is_generic():
    msg = permission_denied_message("approve_leave_request")
    assert "approve_leave_request" not in msg
    assert msg == permission_denied_message("assign_ticket")
