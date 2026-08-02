# What was added (PeopleOps Copilot)

Nothing existing was removed or rewritten — only additive changes plus three
small edits to wire things in. Full write-up: `docs/ai_architecture.md`.

## New backend files
- `app/models/policy_chunk.py`, `app/models/ai_audit_log.py`
- `app/services/ai/` (11 files): `llm_client`, `embeddings`, `vector_store`,
  `policy_rag`, `sql_guardrails`, `sql_agent`, `permissions`, `api_tools`,
  `action_agent`, `router_agent`, `audit`
- `alembic/versions/0017_ai_policy_chunks_and_audit_log.py`
- `scripts/ingest_policies.py`

## Edited backend files (additive only)
- `app/models/__init__.py` — registered the 2 new models
- `app/schemas/chat.py` — added `ChatRequest` (existing stub schemas untouched)
- `app/api/v1/endpoints/chat.py` — added `/policy`, `/sql`, `/actions`,
  `/router` routes; existing `/sessions` 501 stubs untouched
- `app/core/config.py`, `.env.example` — added AI-related settings
- `requirements.txt` — added `anthropic`, `numpy`, `sqlparse`, `httpx`

## New frontend files
- `app/ai-copilot/page.tsx`
- `components/ai/chat-panel.tsx`, `source-list.tsx`, `sql-result-table.tsx`,
  `action-result-card.tsx`

## Edited frontend files (additive only)
- `lib/api.ts` — appended `askPolicy`/`askSql`/`runAction` + types
- `components/layout/sidebar.tsx` — added "AI Copilot" nav item
- `middleware.ts` — added `/ai-copilot` to the protected-route list

## Docs
- `docs/ai_architecture.md`, `docs/ai_permissions_matrix.md`, `docs/ai_eval_results.md`
- `README.md` — new "AI PeopleOps Copilot" section + setup steps

## To run it
```bash
cp backend/.env.example backend/.env   # set ANTHROPIC_API_KEY
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
docker-compose exec api python -m scripts.ingest_policies
```
Then open `http://localhost:3000/ai-copilot`.

## Verified
- Every backend `.py` file (existing + new) passes `python -m py_compile`.
- Every new/edited frontend `.ts`/`.tsx` file passes a `tsc --noEmit` syntax
  pass (errors seen were only "missing @types/react" style noise from not
  having `node_modules` installed in this sandbox — no real syntax errors).
- Not executed end-to-end against a live Claude model in this sandbox (no
  network / API key here) — see the note at the top of
  `docs/ai_eval_results.md`.
