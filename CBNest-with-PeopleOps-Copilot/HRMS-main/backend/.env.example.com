APP_NAME=Mock HRMS API
ENVIRONMENT=dev
APP_TIMEZONE=Asia/Kolkata
DATABASE_URL=sqlite+aiosqlite:///./storage/hrms.db
JWT_SECRET_KEY=change_me
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7
EMPLOYEE_DOCUMENT_UPLOAD_DIR=/app/storage/employee-documents

# --- AI layer (PeopleOps Copilot) ---
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
SQL_AGENT_ENABLED=true
SQL_AGENT_MAX_ROWS=100
POLICY_RAG_TOP_K=4
AI_AUDIT_LOG_ENABLED=true
# The Action Agent calls the app's own REST API over HTTP (loopback) rather
# than touching the DB directly. Point this at wherever uvicorn is bound.
INTERNAL_API_BASE_URL=http://localhost:8000/api/v1

