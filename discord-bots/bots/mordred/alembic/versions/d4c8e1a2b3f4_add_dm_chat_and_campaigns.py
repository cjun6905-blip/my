"""add dm chat quota, consent and outbound campaign queue

Revision ID: d4c8e1a2b3f4
Revises: b7d2e4f6a8c1
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "d4c8e1a2b3f4"
down_revision: Union[str, Sequence[str], None] = "b7d2e4f6a8c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dm_user_preferences",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("greetings_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("opted_in_at", sa.DateTime(), nullable=True),
        sa.Column("opted_out_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        schema="admin",
    )
    op.create_table(
        "dm_daily_usage",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("usage_date", sa.Date(), primary_key=True),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        schema="admin",
    )
    op.create_table(
        "dm_campaigns",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="scheduled"),
        sa.Column("target_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Index("ix_admin_dm_campaign_status_schedule", "status", "scheduled_at"),
        schema="admin",
    )
    op.create_table(
        "dm_deliveries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.BigInteger(), sa.ForeignKey("admin.dm_campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.String(200), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("campaign_id", "user_id", name="uq_dm_delivery_campaign_user"),
        sa.Index("ix_admin_dm_delivery_queue", "status", "next_attempt_at"),
        schema="admin",
    )


def downgrade() -> None:
    op.drop_table("dm_deliveries", schema="admin")
    op.drop_table("dm_campaigns", schema="admin")
    op.drop_table("dm_daily_usage", schema="admin")
    op.drop_table("dm_user_preferences", schema="admin")
