"""users: право менять глобальные настройки интеграций (кроме is_admin)

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_edit_integration_settings",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("users", "can_edit_integration_settings", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "can_edit_integration_settings")
