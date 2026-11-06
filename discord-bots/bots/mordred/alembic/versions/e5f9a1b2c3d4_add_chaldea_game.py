"""add isolated chaldea game schema

Revision ID: e5f9a1b2c3d4
Revises: d4c8e1a2b3f4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f9a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d4c8e1a2b3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS chaldea")
    op.create_table(
        "player_profiles",
        sa.Column("user_id", sa.String(length=50), primary_key=True),
        sa.Column("quartz", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("pity_counter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_table(
        "currency_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_index("ix_chaldea_ledger_user_created", "currency_ledger", ["user_id", "created_at"], schema="chaldea")
    op.create_table(
        "daily_claims",
        sa.Column("user_id", sa.String(length=50), primary_key=True),
        sa.Column("claim_date", sa.Date(), primary_key=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_table(
        "owned_servants",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("servant_id", sa.String(length=80), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("np_level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("shards", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "servant_id", name="uq_chaldea_owned_user_servant"),
        schema="chaldea",
    )
    op.create_index("ix_chaldea_owned_user", "owned_servants", ["user_id"], schema="chaldea")
    op.create_table(
        "teams",
        sa.Column("user_id", sa.String(length=50), primary_key=True),
        sa.Column("servant_ids", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_table(
        "summon_rolls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("banner_id", sa.String(length=80), nullable=False, server_default="story"),
        sa.Column("interaction_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("draw_count", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_table(
        "battles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("challenger_id", sa.String(length=50), nullable=False),
        sa.Column("opponent_id", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.Column("winner_id", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_index("ix_chaldea_battle_challenger_status", "battles", ["challenger_id", "status"], schema="chaldea")
    op.create_index("ix_chaldea_battle_opponent_status", "battles", ["opponent_id", "status"], schema="chaldea")
    op.create_table(
        "battle_actions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("battle_id", sa.String(length=36), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("battle_id", "turn", "user_id", name="uq_chaldea_action_battle_turn_user"),
        schema="chaldea",
    )


def downgrade() -> None:
    for table in (
        "battle_actions",
        "battles",
        "summon_rolls",
        "teams",
        "owned_servants",
        "daily_claims",
        "currency_ledger",
        "player_profiles",
    ):
        op.drop_table(table, schema="chaldea")
    op.execute("DROP SCHEMA IF EXISTS chaldea")

