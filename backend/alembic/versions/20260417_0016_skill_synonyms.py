"""skill_synonyms: кэш синонимов навыков

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-17

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_synonyms",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_norm", sa.String(length=128), nullable=False),
        sa.Column("canonical", sa.String(length=128), nullable=False),
        sa.Column(
            "synonyms_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="llm"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_skill_synonyms_canonical_norm",
        "skill_synonyms",
        ["canonical_norm"],
        unique=True,
    )
    op.alter_column("skill_synonyms", "synonyms_json", server_default=None)
    op.alter_column("skill_synonyms", "source", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_skill_synonyms_canonical_norm", table_name="skill_synonyms")
    op.drop_table("skill_synonyms")
