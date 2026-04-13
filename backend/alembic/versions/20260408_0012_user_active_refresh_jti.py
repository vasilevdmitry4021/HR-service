"""users: jti активной refresh-сессии (ротация refresh-токенов)

Revision ID: 0012
Revises: 0011
Create Date: 2026-04-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("active_refresh_jti", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "active_refresh_jti")
