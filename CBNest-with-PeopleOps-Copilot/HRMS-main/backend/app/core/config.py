from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mock HRMS API"
    environment: str = "dev"
    app_timezone: str = "Asia/Kolkata"
    database_url: str = "sqlite+aiosqlite:///./storage/hrms.db"

    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    policy_upload_dir: str = "/app/storage/hr-policies"
    profile_photo_upload_dir: str = "/app/storage/profile-photos"
    employee_document_upload_dir: str = "/app/storage/employee-documents"

    # --- AI layer (PeopleOps Copilot) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    sql_agent_enabled: bool = True
    sql_agent_max_rows: int = 100
    policy_rag_top_k: int = 4
    ai_audit_log_enabled: bool = True
    internal_api_base_url: str = "http://localhost:8000/api/v1"


settings = Settings()
