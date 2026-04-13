"""Favorites: contact_email, contact_phone

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "favorites",
        sa.Column("contact_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("contact_phone", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("favorites", "contact_phone")
    op.drop_column("favorites", "contact_email")
