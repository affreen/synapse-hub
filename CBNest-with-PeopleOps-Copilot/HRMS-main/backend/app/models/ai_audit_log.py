from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AIAuditLog(Base):
    """
    One row per /api/v1/chat/* request, success or refusal or error alike.
    Never stores: JWTs/access tokens, passwords, bank/PAN fields, or raw
    payroll figures — see app/services/ai/audit.py.
    """

    __tablename__ = "ai_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    action_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    records_accessed: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Observability: total request wall-clock time, and the LLM token usage
    # actually billed for this request (summed across every Claude call the
    # request made — e.g. SQL Agent's generate-then-summarize both count).
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_call_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stable guardrail/failure code (e.g. FORBIDDEN_COLUMN, ROLE_SCOPE_VIOLATION,
    # PERMISSION_DENIED) — null for successful/non-refused requests. Lets the
    # observability dashboard break refusals down by *why*, not just count them.
    refusal_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
