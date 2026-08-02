"""ai audit log refusal reason

Revision ID: 0019_ai_audit_log_refusal_reason
Revises: 0018_ai_audit_log_observability_fields
Create Date: 2026-08-02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_ai_audit_log_refusal_reason"
down_revision: Union[str, None] = "0018_ai_audit_log_observability_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("ai_audit_logs") as batch_op:
        batch_op.add_column(sa.Column("refusal_reason", sa.String(length=50), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_audit_logs") as batch_op:
        batch_op.drop_column("refusal_reason")
