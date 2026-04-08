"""Таблица estaff_exports (история выгрузок в e-staff)

Revision ID: 0006
Revises: 0005
Create Date: 2025-03-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "estaff_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hh_resume_id", sa.String(length=128), nullable=False),
        sa.Column("estaff_candidate_id", sa.String(length=256), nullable=True),
        sa.Column("estaff_vacancy_id", sa.String(length=256), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_estaff_exports_user_id"),
        "estaff_exports",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_estaff_exports_hh_resume_id"),
        "estaff_exports",
        ["hh_resume_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_estaff_exports_created_at"),
        "estaff_exports",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_estaff_exports_created_at"), table_name="estaff_exports")
    op.drop_index(op.f("ix_estaff_exports_hh_resume_id"), table_name="estaff_exports")
    op.drop_index(op.f("ix_estaff_exports_user_id"), table_name="estaff_exports")
    op.drop_table("estaff_exports")
