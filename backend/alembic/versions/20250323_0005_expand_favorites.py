"""expand favorites with candidate snapshot

Revision ID: 0005
Revises: 0004
Create Date: 2025-03-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "favorites",
        sa.Column("full_name", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("area", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("skills_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("experience_years", sa.Integer(), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("age", sa.Integer(), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("salary_amount", sa.Integer(), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("salary_currency", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("llm_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "favorites",
        sa.Column("llm_summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("favorites", "llm_summary")
    op.drop_column("favorites", "llm_score")
    op.drop_column("favorites", "salary_currency")
    op.drop_column("favorites", "salary_amount")
    op.drop_column("favorites", "age")
    op.drop_column("favorites", "experience_years")
    op.drop_column("favorites", "skills_snapshot")
    op.drop_column("favorites", "area")
    op.drop_column("favorites", "full_name")
