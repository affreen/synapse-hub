# AI Assistant Eval Set

`eval_set.json` is the formal, machine-readable eval set for the PeopleOps
Copilot (Policy RAG / SQL Agent / HR Action Agent). It's the structured
counterpart to the manual checklist in `docs/ai_eval_results.md` and the
hardcoded cases in `scripts/eval_live.py` — this file is not currently
consumed by either, it's a standalone reference dataset for evaluation
tooling to run against.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Stable identifier for the case |
| `input` | string | The exact user prompt sent to the assistant |
| `role` | `EMPLOYEE` \| `MANAGER` \| `ADMIN` | Role of the user issuing the prompt |
| `expected_route` | `POLICY_RAG` \| `SQL_AGENT` \| `HR_ACTION` | Which agent should handle the request |
| `expected_behavior` | string | The pass condition category (see below) |
| `notes` | string | Specific, checkable detail for that case (expected source, forbidden column, etc.) |

### `expected_behavior` values

- `answer_with_source` — grounded answer citing a real policy in `sources`
- `answer_no_match` — no matching policy; graceful "don't know", empty `sources`, no hallucination
- `refuse` — request is rejected (forbidden column, destructive SQL, role-scope violation, or role-permission check)
- `return_rows` — SQL query executes and returns real rows
- `scoped_to_self` — SQL query is auto-scoped to the requesting employee
- `call_create_ticket_api` / `call_create_leave_request_api` — a specific, non-high-impact tool call executes directly
- `await_confirmation_then_execute` — high-impact action returns `requires_confirmation: true` + `pending_action`, and only mutates data after the user confirms
- `not_applicable` — no matching tool exists in `TOOL_CATALOG`; nothing executes

## Coverage

23 cases across all three agents, including the security/refusal suite from
`docs/ai_eval_results.md` §2–4 (forbidden columns, destructive SQL, role-scope
violations, prompt injection via retrieved policy text, and permission checks
on high-impact actions).
