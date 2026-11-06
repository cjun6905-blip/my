"""add Chaldea growth resources

Revision ID: f6a1b2c3d4e5
Revises: e5f9a1b2c3d4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e5f9a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player_profiles",
        sa.Column("qp", sa.Integer(), nullable=False, server_default="2000"),
        schema="chaldea",
    )
    op.add_column(
        "player_profiles",
        sa.Column("training_exp", sa.Integer(), nullable=False, server_default="300"),
        schema="chaldea",
    )
    op.add_column(
        "currency_ledger",
        sa.Column(
            "resource_type",
            sa.String(length=30),
            nullable=False,
            server_default="quartz",
        ),
        schema="chaldea",
    )


def downgrade() -> None:
    op.drop_column("currency_ledger", "resource_type", schema="chaldea")
    op.drop_column("player_profiles", "training_exp", schema="chaldea")
    op.drop_column("player_profiles", "qp", schema="chaldea")
