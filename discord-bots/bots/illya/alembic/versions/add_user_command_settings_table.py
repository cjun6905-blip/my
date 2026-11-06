"""add_user_command_settings_table

Revision ID: add_user_command_settings
Revises: add_user_tool_settings
Create Date: 2026-03-29 13:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = "add_user_command_settings"
down_revision: Union[str, Sequence[str], None] = "add_summarized_conv_blocks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create user schema if not exists (user is a reserved keyword)
    op.execute(text('CREATE SCHEMA IF NOT EXISTS "user"'))

    # Create user_command_settings table in user schema using raw SQL
    op.execute(
        text("""
        CREATE TABLE "user".user_command_settings (
            id SERIAL NOT NULL,
            user_id VARCHAR(50) NOT NULL,
            enabled_commands JSON,
            created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
            PRIMARY KEY (id),
            UNIQUE (user_id)
        )
    """)
    )

    # Create index on id
    op.execute(
        text("""
        CREATE INDEX ix_user_command_settings_id ON "user".user_command_settings (id)
    """)
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index and table
    op.execute(text('DROP INDEX IF EXISTS "user".ix_user_command_settings_id'))
    op.execute(text('DROP TABLE IF EXISTS "user".user_command_settings'))
    # Note: We don't drop the schema as it might contain other tables
