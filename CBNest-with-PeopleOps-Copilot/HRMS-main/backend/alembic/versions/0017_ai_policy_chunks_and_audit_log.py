"""ai policy chunks and audit log

Revision ID: 0017_ai_policy_chunks_and_audit_log
Revises: 0016_employee_documents_uploaded_by
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_ai_policy_chunks_and_audit_log"
down_revision: Union[str, None] = "0016_employee_documents_uploaded_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "policy_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("hr_policies.id"), index=True, nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
    )

    op.create_table(
        "ai_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("employees.id"), index=True, nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=50), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=True),
        sa.Column("action_status", sa.String(length=30), nullable=True),
        sa.Column("records_accessed", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("ai_audit_logs")
    op.drop_table("policy_chunks")
