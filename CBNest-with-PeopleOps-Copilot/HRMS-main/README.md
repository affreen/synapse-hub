<img width="2866" height="1274" alt="image" src="https://github.com/user-attachments/assets/4b4defd5-663f-45d1-b9e3-f9adbcfabbae" />

# CB Nest

**CB Nest** is a full-stack HR Management System built for hands-on learning. It covers real-world business workflows — employee lifecycle, attendance, leave approvals, payroll, ticketing, and more — using a modern stack (FastAPI + Next.js + Docker). Use it to understand how production-grade HRMS platforms work, and extend it with your own AI features.

> 📖 **New here?** Start with the [Learner Guide](docs/Learner_Guide.md) for a complete walkthrough of the project architecture, database, and how to explore the code.

## Overview

This project provides a working HRMS platform with authentication, employee operations, attendance, leave management, communication features, finance data views, and ticketing workflows.

It is designed as a practical base for AI feature integration (RAG, assistants, agent workflows) without rebuilding core HR modules from scratch.


## Tech Stack

- Frontend: Next.js 15, React 19, Tailwind CSS
- Backend: FastAPI, SQLAlchemy (async), Pydantic v2
- Database: SQLite
- Migrations: Alembic
- Orchestration: Docker Compose

## Features

- JWT auth with role-aware access (ADMIN, MANAGER, EMPLOYEE)
- Employee directory with search, filters, and pagination
- Attendance clock in/clock out with status and mode tracking
- Leave balances and leave request workflow
- Announcements and polls
- Team calendar (leaves, WFH, holidays, birthdays)
- My Profile edits, profile photo upload, job history, documents
- Finance views (salary, statutory, payroll history)
- Tickets with assignment, status updates, onboarding tasks
- HR policy upload/download library
- Admin/Manager employee document upload flow (APPOINTMENT, TAX, PAYSLIP, OTHER)
- My Documents with search, view, and download; delete is allowed only for `OTHER` document type
- Password-protected PDF payslips (DOB in `DD-MM-YY`) for generated and uploaded payslips
- Notification bell for announcements, polls, ticket assignment, ticket status, leave decision, and employee-document uploads by others (not self-uploads)
- **NovaWorks PeopleOps Copilot** (`/api/v1/chat/*`, `/ai-copilot` in the app): AI Policy RAG assistant, natural-language SQL agent, and HR task automation agent — see [AI Copilot](#ai-peopleops-copilot) below

## Repository Structure

```text
.
|-- backend/
|   |-- alembic/
|   |   |-- versions/
|   |   `-- env.py
|   |-- app/
|   |   |-- api/v1/endpoints/
|   |   |-- core/
|   |   |-- db/
|   |   |-- models/
|   |   |-- schemas/
|   |   `-- services/
|   |-- scripts/
|   |   `-- seed.py
|   |-- storage/
|   |   |-- hr-policies/
|   |   `-- profile-photos/
|   |-- .env.example
|   |-- alembic.ini
|   |-- Dockerfile
|   `-- requirements.txt
|-- frontend/
|   |-- app/
|   |   |-- announcements/
|   |   |-- attendance/
|   |   |-- dashboard/
|   |   |-- employees/
|   |   |-- finance/
|   |   |-- hr-policies/
|   |   |-- leaves/
|   |   |-- login/
|   |   |-- me/
|   |   |-- organization/
|   |   |-- polls/
|   |   |-- team-calendar/
|   |   `-- tickets/
|   |-- components/
|   |   |-- layout/
|   |   `-- ui/
|   |-- lib/
|   |   `-- api.ts
|   |-- Dockerfile
|   |-- middleware.ts
|   `-- package.json
|-- docs/
|   |-- api/
|   |-- Learner_Guide.md
|   |-- PRD.md
|   `-- db_tables_samples.md
|-- docker-compose.yml
`-- README.md
```

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2)
  - On Windows: install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure the **WSL 2 backend** is enabled
- **Git**


## Quick Start

First-time setup:

```bash
git clone <repo-url>
cd HRMS-main
cp backend/.env.example backend/.env
```

> Edit `backend/.env` and set `ANTHROPIC_API_KEY` if you want the PeopleOps
> Copilot (AI features) to work — everything else runs without it.


For PowerShell on Windows:

```powershell
Copy-Item backend/.env.example backend/.env
```

Then run from repository root:

```bash
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

Open:

- App: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API redoc: `http://localhost:8000/redoc`

Verify everything is working:

```bash
docker-compose ps
```

## Default Credentials

- Admin: `admin@mock-hrms.dev` / `password123`
- Manager: `manager@mock-hrms.dev` / `password123`
- Employee: `employee@mock-hrms.dev` / `password123`

## AI PeopleOps Copilot

An AI layer sits alongside the existing HRMS backend/frontend without touching its business logic. Three agents, all under `/api/v1/chat/*`:

| Endpoint | Agent | What it does |
|---|---|---|
| `POST /api/v1/chat/policy` | Policy RAG Assistant | Answers HR policy questions, grounded in `hr_policies` (chunked + embedded), with cited sources |
| `POST /api/v1/chat/sql` | SQL Agent | Turns a question into a single read-only `SELECT`, validated and role-scoped, over employees/projects/skills/leave/tickets |
| `POST /api/v1/chat/actions` | HR Action Agent | Performs leave requests, approvals, tickets, announcements, and project assignments by calling the **existing** REST endpoints as tools (never writes to the DB directly) |
| `POST /api/v1/chat/router` | Router (optional) | Classifies a message into `POLICY_QA` / `SQL_QUERY` / `HR_ACTION` / `UNKNOWN` |

In the app: **Sidebar → AI Copilot** (`/ai-copilot`), with three tabs matching the three agents above.

### Setup

1. Get an Anthropic API key and set it in `backend/.env`:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
2. Seed the DB as usual (`docker-compose exec api python scripts/seed.py`) — this also seeds 22 HR policy `.md` files.
3. Index the policy library into the RAG vector store:
   ```bash
   docker-compose exec api python -m scripts.ingest_policies
   ```
   Re-run this any time policies are added/edited (e.g. after `POST /api/v1/hr-policies/upload`).
4. Open `http://localhost:3000/ai-copilot` and log in with any seeded account.

### Design notes

- **Embeddings** are generated locally with TF-IDF (numpy only) — no external embedding API or model download required. See `docs/ai_architecture.md` for why.
- **SQL Agent** never runs anything but a single validated `SELECT`; forbidden columns (passwords, bank/PAN, salary, photos) are blocked at the prompt, the validator, and the result layer.
- **Action Agent** calls the app's own FastAPI endpoints over HTTP with the caller's own JWT — it has no elevated privileges and no direct DB access.
- High-impact actions (approve/reject leave, create announcement, assign to project, assign ticket) require an explicit confirm step.
- Every `/chat/*` call writes one row to `ai_audit_logs`, success or refusal alike.

Full details: [`docs/ai_architecture.md`](docs/ai_architecture.md), [`docs/ai_permissions_matrix.md`](docs/ai_permissions_matrix.md), [`docs/ai_eval_results.md`](docs/ai_eval_results.md).

### Running the Evals

The formal eval set for the AI assistant lives in [`backend/evals/eval_set.json`](backend/evals/eval_set.json) — 23 structured cases (`input`, `role`, `expected_route`, `expected_behavior`) covering Policy RAG, SQL Agent, and HR Action Agent, including the security/refusal suite from `docs/ai_eval_results.md`. Schema details: [`backend/evals/README.md`](backend/evals/README.md).

`backend/scripts/eval_live.py` runs these prompts against the **real, running API and a real Claude model** (costs tokens; a few prompts genuinely mutate data — leave requests, tickets, approvals). Prerequisites: stack up, migrated, seeded, and policies indexed (see [Setup](#setup) above), plus `ANTHROPIC_API_KEY` set in `backend/.env`.

```bash
docker-compose exec api python -m scripts.eval_live
```

It prints a `[PASS]`/`[FAIL]` line per case and a final summary, and exits non-zero if anything failed.

For fast, free, deterministic checks that don't need an API key or a running stack, use the mocked pytest suite instead:

```bash
docker-compose exec api pytest
```

## Configuration

Backend environment file: `backend/.env`

Use `backend/.env.example` as reference. Current key settings:

- `DATABASE_URL=sqlite+aiosqlite:///./storage/hrms.db`
- `APP_TIMEZONE=Asia/Kolkata`
- JWT settings (`JWT_SECRET_KEY`, expiry values)

## Common Commands

Start services:

```bash
docker-compose up -d
```

Restart API + Web after code changes:

```bash
docker compose restart api web
```

Stop services:

```bash
docker-compose down
```

Run migrations:

```bash
docker-compose exec api alembic -c alembic.ini upgrade head
```

Reseed data:

```bash
docker-compose exec api python scripts/seed.py
```

Index/re-index HR policies for the AI Policy Assistant:

```bash
docker-compose exec api python -m scripts.ingest_policies
```

Run the AI assistant's formal eval set live (costs tokens; see [Running the Evals](#running-the-evals)):

```bash
docker-compose exec api python -m scripts.eval_live
```

Optional one-time migration (legacy payslip files to DOB-password-protected PDFs):

```bash
docker compose exec api python scripts/migrate_payslips_to_encrypted_pdf.py
```

Check containers:

```bash
docker-compose ps
```

## Reset Database

On macOS/Linux:

```bash
docker-compose down
rm -f backend/storage/hrms.db
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

On PowerShell:

```powershell
docker-compose down
Remove-Item backend\storage\hrms.db -Force -ErrorAction SilentlyContinue
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

## API Notes

- API base path: `/api/v1`
- Health checks:
  - `/health`
  - `/api/v1/health`
- Standard response envelope:
  - Success: `{ "success": true, "data": ..., "error": null }`
  - Error: `{ "success": false, "data": null, "error": { "code": "...", "message": "..." } }`
- Document uploads:
  - Employee self-upload: `POST /api/v1/employees/me/documents`
  - Employee self-delete: `DELETE /api/v1/employees/me/documents/{document_id}` (`OTHER` type only)
  - Admin/Manager upload for any employee: `POST /api/v1/employees/{employee_id}/documents`
  - Admin/Manager payslip upload: `POST /api/v1/employees/{employee_id}/documents/payslip`

## Troubleshooting

- If frontend shows stale build/runtime issues:
  - `docker-compose restart web`
- If API changes are not reflected:
  - `docker-compose restart api`
- If migration or seed fails:
  - reset DB using the commands above, then migrate and seed again

## Documentation

- Learner guide: [`Learner_Guide.md`](docs/Learner_Guide.md) — full project walkthrough, architecture, database schema, learning path
- Product requirements: [`PRD.md`](docs/PRD.md)
- Database schema reference: [`db_tables_samples.md`](docs/db_tables_samples.md)
- AI chat endpoint contracts: `docs/api/`


Copyright (c) Codebasics. All rights reserved.


