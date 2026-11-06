"""add battle spectator comments

Revision ID: h8c3d4e5f6a7
Revises: g7b2c3d4e5f6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "g7b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "battle_comments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("battle_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=False),
        sa.Column("content", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        schema="chaldea",
    )
    op.create_index("ix_chaldea_comments_battle_id", "battle_comments", ["battle_id", "id"], schema="chaldea")
    op.create_index("ix_chaldea_comments_user_created", "battle_comments", ["user_id", "created_at"], schema="chaldea")


def downgrade() -> None:
    op.drop_table("battle_comments", schema="chaldea")
