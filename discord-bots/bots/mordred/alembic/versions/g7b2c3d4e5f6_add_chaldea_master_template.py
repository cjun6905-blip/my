"""add Chaldea master template selection

Revision ID: g7b2c3d4e5f6
Revises: f6a1b2c3d4e5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f6a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player_profiles",
        sa.Column(
            "master_template_id",
            sa.String(length=40),
            nullable=False,
            server_default="chaldea_uniform",
        ),
        schema="chaldea",
    )


def downgrade() -> None:
    op.drop_column("player_profiles", "master_template_id", schema="chaldea")
