"""ai audit log observability fields

Revision ID: 0018_ai_audit_log_observability_fields
Revises: 0017_ai_policy_chunks_and_audit_log
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_ai_audit_log_observability_fields"
down_revision: Union[str, None] = "0017_ai_policy_chunks_and_audit_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_audit_logs") as batch_op:
        batch_op.add_column(sa.Column("latency_ms", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("input_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("output_tokens", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("llm_call_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_audit_logs") as batch_op:
        batch_op.drop_column("llm_call_count")
        batch_op.drop_column("output_tokens")
        batch_op.drop_column("input_tokens")
        batch_op.drop_column("latency_ms")
