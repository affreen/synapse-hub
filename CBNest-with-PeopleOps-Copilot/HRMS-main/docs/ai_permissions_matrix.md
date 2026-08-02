# AI Permissions Matrix

This is the human-readable form of `backend/app/services/ai/permissions.py`
(`TOOL_PERMISSIONS`, `HIGH_IMPACT_TOOLS`) — the two are kept in sync by hand;
if you change one, change the other.

## Tool permissions (HR Action Agent)

| Tool | Minimum role | Confirmation required? | Notes |
|---|---|---|---|
| `create_leave_request` | EMPLOYEE | No | Balance/date validation happens in the real `POST /leaves/requests` endpoint |
| `check_leave_balance` | EMPLOYEE | No | Own balance only (`GET /leaves/balances/me`) |
| `check_my_leave_requests` | EMPLOYEE | No | Own requests only (`GET /leaves/requests/me`) |
| `create_ticket` | EMPLOYEE | No | |
| `check_ticket_status` | EMPLOYEE | No | Own + assigned tickets only, enforced by `GET /tickets?mine=true` |
| `view_own_projects` | EMPLOYEE | No | Routed through the SQL Agent, scoped to `employee_id = caller` |
| `search_employees_by_skill` | EMPLOYEE | No | Routed through the SQL Agent; catalog-style, no sensitive fields |
| `update_ticket_status` | EMPLOYEE | No | Real endpoint (`POST /tickets/{id}/status`) still enforces "own/assigned, or manager/admin" |
| `approve_leave_request` | MANAGER | **Yes** | |
| `reject_leave_request` | MANAGER | **Yes** | |
| `assign_ticket` | MANAGER | **Yes** | |
| `create_announcement` | MANAGER | **Yes** | |
| `assign_employee_to_project` | MANAGER | **Yes** | |

ADMIN inherits everything MANAGER can do (role rank ADMIN > MANAGER > EMPLOYEE).

## SQL Agent access

| Data | EMPLOYEE | MANAGER | ADMIN |
|---|---|---|---|
| Own leave balance / requests / tickets | Yes | Yes | Yes |
| Another employee's leave/tickets/job history | No | Direct reports only (heuristic) | Yes |
| Employee directory / department / project catalog | Yes | Yes | Yes |
| Skill search across employees | Yes (name/department only, no sensitive fields) | Yes | Yes |
| Raw SQL shown in the UI | No | Yes | Yes |
| Forbidden columns (password, DOB, bank, PAN, salary, photo, pf_uan, esi_no) | Never | Never | Never |

## Policy RAG

All roles get identical access — HR policy is not role-sensitive in this app. The assistant still won't answer beyond what's in the indexed policy library, regardless of role.

## Refusal behavior

Refusals are always generic ("You do not have permission to perform that action.") and never confirm or deny that the underlying record exists — e.g. an employee asking to approve someone else's leave gets the same message whether or not that leave request exists, so the response can't be used to enumerate valid IDs.

## Full end-to-end matrix (mirrors the assignment brief)

| AI Capability | Employee | Manager | Admin |
|---|---:|---:|---:|
| Ask HR policy questions | Yes | Yes | Yes |
| Ask own leave balance | Yes | Yes | Yes |
| Ask another employee's leave balance | No | Direct reports only | Yes |
| View own project assignments | Yes | Yes | Yes |
| View all project assignments | No (catalog query only) | Limited (SQL Agent, own team via manager_id) | Yes |
| Search employees by skill | Yes (limited fields) | Yes | Yes |
| Generate SQL over HR data | Limited (own data + catalog) | Limited (team + catalog) | Yes |
| View raw SQL in UI | No | Yes | Yes |
| Create own leave request | Yes | Yes | Yes |
| Approve/reject leave | No | Yes (confirm required) | Yes (confirm required) |
| Create ticket | Yes | Yes | Yes |
| Assign/update ticket | Update own/assigned only | Assign: yes (confirm required) | Yes |
| Create announcement | No | Yes (confirm required) | Yes (confirm required) |
| Assign employee to project | No | Yes (confirm required) | Yes (confirm required) |
| Access payroll data | Blocked | Blocked | Blocked (forbidden columns are never selectable by AI, even for admins — payroll must be viewed through the existing Finance UI, not the AI layer) |
| Access bank/PAN/password fields | No | No | No |
