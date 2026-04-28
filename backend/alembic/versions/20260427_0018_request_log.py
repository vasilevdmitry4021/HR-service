"""create request_log table

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "request_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("query_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_email", sa.String(length=320), nullable=True),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("route", sa.String(length=256), nullable=False),
        sa.Column("route_tag", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("request_body_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("search_metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("integration_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_request_log_request_id", "request_log", ["request_id"], unique=True)
    op.create_index("ix_request_log_query_id", "request_log", ["query_id"], unique=False)
    op.create_index("ix_request_log_user_id", "request_log", ["user_id"], unique=False)
    op.create_index("ix_request_log_route_tag", "request_log", ["route_tag"], unique=False)
    op.create_index("ix_request_log_error_type", "request_log", ["error_type"], unique=False)
    op.create_index("ix_request_log_created_at", "request_log", ["created_at"], unique=False)
    op.create_index(
        "ix_request_log_created_at_route_tag",
        "request_log",
        ["created_at", "route_tag"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_request_log_created_at_route_tag", table_name="request_log")
    op.drop_index("ix_request_log_created_at", table_name="request_log")
    op.drop_index("ix_request_log_error_type", table_name="request_log")
    op.drop_index("ix_request_log_route_tag", table_name="request_log")
    op.drop_index("ix_request_log_user_id", table_name="request_log")
    op.drop_index("ix_request_log_query_id", table_name="request_log")
    op.drop_index("ix_request_log_request_id", table_name="request_log")
    op.drop_table("request_log")
