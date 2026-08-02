I # AI Architecture — NovaWorks PeopleOps Copilot

## 1. Where the AI layer sits

The AI layer is additive to the existing CB Nest app. No existing model, endpoint, or business rule was modified to make room for it (leaves.py, tickets.py, announcements.py, employees.py are untouched). New pieces:

```
backend/app/models/policy_chunk.py       # new table: RAG vector store
backend/app/models/ai_audit_log.py       # new table: AI audit log
backend/app/services/ai/
  llm_client.py       # single Claude wrapper used by all agents
  embeddings.py        # local TF-IDF embeddings (no external API)
  vector_store.py       # cosine-similarity search over policy_chunks
  policy_rag.py          # ingestion + grounded answer generation
  sql_guardrails.py       # SELECT-only validation, forbidden columns, table allow-list
  sql_agent.py              # NL -> SQL -> validated -> executed -> summarized
  permissions.py             # AI tool permission matrix (code form of docs/ai_permissions_matrix.md)
  api_tools.py                # HTTP wrappers around the app's OWN REST API
  action_agent.py               # intent extraction, permission check, confirmation, tool execution
  router_agent.py                # intent classifier (used standalone by /router, and inside graph.py)
  graph.py                        # LangGraph orchestration for POST /chat/graph
  audit.py                        # writes ai_audit_logs
backend/app/api/v1/endpoints/chat.py   # extended (not replaced) with /policy /sql /actions /router /graph
backend/scripts/ingest_policies.py     # one-off/re-run indexing script
frontend/app/ai-copilot/page.tsx       # new page
frontend/components/ai/*               # chat panel + sub-components
```

The existing `/chat/sessions` and `/chat/sessions/{id}/messages` Phase-3 stubs are left as-is (still return 501) — they were a different, session/thread-based chat concept than what this assignment asks for, so we did not repurpose them.

## 2. Request flow

```
User message (Next.js /ai-copilot)
   -> POST /api/v1/chat/{policy|sql|actions} with JWT (same auth as the rest of the app)
   -> get_current_user() decodes JWT, loads Employee (id, role) — no separate AI auth path
   -> route to the matching agent
   -> agent applies its own guardrails (RAG grounding / SQL validation+scoping / tool permission)
   -> Policy RAG and SQL Agent: read-only, respond directly
   -> Action Agent: calls the app's own REST endpoint over HTTP with the user's JWT (never touches DB directly)
   -> ai_audit_logs row written (success, refusal, or error)
   -> JSON response: {"success", "data", "error"} (matches this app's existing response envelope)
```

The three endpoints above are mode-tab-driven — the frontend already knows which agent to call. `POST /api/v1/chat/graph` (§7) is the auto-routed alternative: one endpoint, intent classified automatically, for a free-form chat experience instead of explicit mode tabs.

## 3. Critical architecture rule: agents never write to the DB

The Action Agent's only way to create/modify data is `services/ai/api_tools.py`, which makes real HTTP calls to `leaves.py` / `tickets.py` / `announcements.py` / `employees.py` endpoints, forwarding the **caller's own JWT**. Every existing validation (leave balance checks, role checks, overlap checks, `require_roles`) applies exactly as it would if the user had clicked a button in the UI. The agent has no elevated privileges, no service-layer bypass, and no direct `INSERT`/`UPDATE`/`DELETE` capability anywhere in its code.

Two read-only "actions" (`view_own_projects`, `search_employees_by_skill`) are routed to the **SQL Agent** instead of a REST endpoint, because:
- `GET /employees/{id}/projects` is restricted to ADMIN/MANAGER in the existing app (an employee viewing their own assignments would get a 403), and
- there is no skill-search endpoint in the app at all.

Both are pure reads scoped to the current user/role by the SQL Agent's own guardrails, so this doesn't create a write bypass — it only adds a safe read path the REST API doesn't otherwise expose.

## 4. Policy RAG

**Ingestion** (`policy_rag.ingest_all_policies`): for every `hr_policies` row, extract text (`content` field if set, else read `file_path` from disk — `.md`/`.txt` directly, `.pdf` via `pypdf`, matching exactly how `hr_policies.py`'s upload endpoint stores policies today). Paragraph-aware chunking (~500 chars, 80-char overlap) produces `PolicyChunk` rows.

**Embeddings**: TF-IDF fit over the whole chunk corpus (numpy only, `services/ai/embeddings.py`). This was chosen over a hosted embeddings API or a downloaded sentence-transformer model because:
- it requires no network access or model download at build/runtime,
- it's deterministic and fast for a policy library of a few dozen documents,
- the assignment explicitly allows "existing database field" as a vector store, and TF-IDF over a closed, well-defined HR policy corpus performs well for keyword-heavy queries like "sick leave", "half-day", "WFH".

Swapping in a hosted embedding model later only requires re-implementing `embed_text`/`fit_vocabulary` — `vector_store.py` and `policy_rag.py` are agnostic to how vectors are produced.

**Retrieval + generation**: cosine similarity search (`vector_store.search`) returns the top-k chunks (default 4). If the best score is below `MIN_RELEVANCE_SCORE`, the assistant explicitly says it doesn't have enough information rather than guessing. Retrieved chunks are wrapped in the prompt as **untrusted reference data**, with an explicit instruction never to follow embedded instructions — this defends against a prompt-injection payload planted inside an uploaded policy document (see the Security Prompt suite in `docs/ai_eval_results.md`).

## 5. SQL Agent

`sql_agent.py` builds a schema description limited to the assignment's "Recommended Tables" (mapped onto this repo's actual table/column names), asks Claude for a single SQL statement as JSON, then runs it through `sql_guardrails.validate_sql`:

1. Must start with `SELECT`/`WITH`.
2. Exactly one statement (via `sqlparse.split`).
3. No blocked keywords (`INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`CREATE`/`REPLACE`/`TRUNCATE`/`PRAGMA`/`ATTACH`/`DETACH`/...).
4. No forbidden columns referenced (`hashed_password`, `date_of_birth`, `profile_photo_*`, `current_salary_usd`, `bank_*`, `pan_*`, `pf_uan`, `esi_no`) — matches `Employee` model exactly.
5. No comments, no stacked statements.
6. Table allow-list (`ALLOWED_TABLES`).
7. `LIMIT` enforced/rewritten to `<= SQL_AGENT_MAX_ROWS` (default 100, hard cap 200).

If any check fails, nothing executes and the user gets a generic, non-leaking refusal.

**Role scoping** is enforced two ways: (a) the system prompt tells the model the exact scoping rule for the caller's role, and (b) `_heuristic_role_scope_check` inspects the validated SQL afterward as defense-in-depth. **Known limitation**: (b) is regex/heuristic, not a formally verified query rewrite — for example it can't guarantee a MANAGER's join expresses "my direct reports" correctly in every possible phrasing. A production system should replace free-form LLM SQL generation with parameterized query templates or a server-side query-rewriting layer for anything beyond simple lookups.

Result rows are passed through `strip_forbidden_fields` as a second, independent layer of defense (in case a forbidden column ever slipped through, e.g. via `SELECT *`).

## 6. HR Action Agent

`action_agent.py` extracts `(tool_name, arguments)` from the message via Claude structured output, checks `services/ai/permissions.py` (imported by nothing else, single source of truth), and either:
- executes immediately (low-impact tools: apply leave, create ticket, check balance, etc.), or
- returns `requires_confirmation: true` + a `pending_action` object for high-impact tools (`approve_leave_request`, `reject_leave_request`, `create_announcement`, `assign_employee_to_project`, `assign_ticket`). The frontend shows Confirm/Cancel buttons; the next request echoes `pending_action` back, and only then is the tool actually executed.

Permission checks happen **before** a confirmation prompt is ever shown, so an unauthorized user never even sees a preview of an action they can't perform.

## 7. LangGraph orchestration (`POST /chat/graph`)

Additive, not a replacement: `/chat/policy`, `/chat/sql`, `/chat/actions` are untouched. `services/ai/graph.py` builds a `langgraph.graph.StateGraph` with one node per step of the requested pipeline:

```
START -> load_user_context -> classify_intent -> route ->
  { policy_rag_node | sql_agent_node | hr_action_node | unhandled_node } ->
  permission_check -> generate_final_response -> audit_log -> END
```

- **load_user_context** re-fetches the `Employee` row from the DB by `user_id`, rather than trusting only the role baked into the caller's JWT — keeps the graph correct even against a stale-but-still-valid token.
- **classify_intent** calls `router_agent.classify_intent` (the same classifier `/chat/router` already exposed standalone, previously unused by the actual chat flow — this is now its first real caller). A `pending_action` reply always short-circuits straight to `HR_ACTION` without re-classifying.
- **route** dispatches to whichever of the three existing agents matches the classified intent, calling `policy_rag.answer_policy_question` / `sql_agent.generate_and_run_sql` / `action_agent.handle_action_request` directly — no agent logic is duplicated or reimplemented here.
- **permission_check** is a defense-in-depth checkpoint, not a second independent permission system: it re-verifies `permissions.is_tool_permitted` for whatever `tool_called` the HR Action Agent returned, using the exact same function the agent already checked internally. If a bug ever let an unpermitted `tool_called` through with a success status, this node catches it and downgrades the result to a refusal before it reaches the response or the audit log.
- **generate_final_response** normalizes the three agents' differently-shaped results (`sources` vs `sql`/`rows` vs `tool_called`/`action_status`) into one response envelope.
- **audit_log** writes the same `ai_audit_logs` row shape the three existing endpoints write — `intent`/`tool_name`/`action_status` are derived identically, so the observability dashboard (§ below) behaves the same regardless of which endpoint a request came through.

## 8. Auditability

Every `/chat/*` call — success, refusal, or error — writes one `ai_audit_logs` row: user id, role, original message (truncated to 1000 chars), detected intent, tool/agent used, action status, and any record ids touched. Never logged: JWTs/access tokens, passwords, bank/PAN fields, or raw payroll numbers.

## 9. Security decisions summary

| Risk | Mitigation |
|---|---|
| SQL injection / destructive SQL | Single-statement, SELECT-only, keyword blocklist, table allow-list, `sqlparse`-based parsing (not string matching alone) |
| Sensitive field leakage | Forbidden-column check at prompt, validator, and result layers (3 independent layers) |
| Cross-employee data access | Role-scoped system prompt + heuristic post-check for personal tables (leave/tickets/job history) |
| Unauthorized actions | `permissions.py` checked before any tool call, before any confirmation preview |
| Accidental high-impact actions | Human-in-the-loop confirmation for approve/reject/announce/assign |
| Prompt injection via policy documents | Retrieved content is wrapped and labelled as untrusted data, never as instructions |
| Direct DB mutation by the agent | Architecturally impossible — `api_tools.py` only makes HTTP calls to existing endpoints |
| Silent failures | Every failure path returns a graceful, non-leaking message and is still audit-logged |

## 10. Known limitations

- TF-IDF embeddings are keyword-based, not semantic — a paraphrased question with no shared vocabulary may retrieve nothing. Acceptable for a closed policy corpus; would need a real embedding model at larger/more varied scale.
- MANAGER-level SQL scoping is heuristic (see §5).
- The confirmation flow is stateless (the frontend must echo back `pending_action`), not stored server-side — acceptable for a chat UI, but wouldn't survive a page reload mid-confirmation. `/chat/graph` inherits this same behavior.
- No streaming responses (see assignment Bonus #3) — out of scope for this pass.
- `/chat/graph` has no frontend UI yet — it's reachable directly (see §7), but the `/ai-copilot` chat panel still calls `/chat/policy` / `/chat/sql` / `/chat/actions` per its mode tabs.
