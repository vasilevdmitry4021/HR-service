"""remove telegram source and telegram tables

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM candidate_source_links WHERE source_type = 'telegram'")
    op.execute("DELETE FROM candidate_profiles WHERE source_type = 'telegram'")

    op.drop_index(
        "ix_telegram_message_attachments_message_id",
        table_name="telegram_message_attachments",
    )
    op.drop_table("telegram_message_attachments")

    op.drop_index("uq_telegram_messages_source_tgmsg", table_name="telegram_messages")
    op.drop_index("ix_telegram_messages_source_id", table_name="telegram_messages")
    op.drop_table("telegram_messages")

    op.drop_index("ix_telegram_sync_runs_source_id", table_name="telegram_sync_runs")
    op.drop_table("telegram_sync_runs")

    op.drop_index("ix_telegram_sources_account_id", table_name="telegram_sources")
    op.drop_table("telegram_sources")

    op.drop_index("ix_telegram_accounts_auth_status", table_name="telegram_accounts")
    op.drop_index("ix_telegram_accounts_owner_id", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")


def downgrade() -> None:
    op.create_table(
        "telegram_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_id", sa.String(length=64), nullable=False),
        sa.Column("encrypted_api_hash", sa.LargeBinary(), nullable=False),
        sa.Column("encrypted_session", sa.LargeBinary(), nullable=True),
        sa.Column("phone_hint", sa.String(length=32), nullable=True),
        sa.Column("auth_status", sa.String(length=32), nullable=False),
        sa.Column("pending_auth", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_accounts_owner_id",
        "telegram_accounts",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        "ix_telegram_accounts_auth_status",
        "telegram_accounts",
        ["auth_status"],
        unique=False,
    )

    op.create_table(
        "telegram_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("link", sa.String(length=1024), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=512), nullable=False),
        sa.Column("access_status", sa.String(length=32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("last_message_id", sa.BigInteger(), nullable=True),
        sa.Column("last_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["telegram_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_sources_account_id",
        "telegram_sources",
        ["account_id"],
        unique=False,
    )

    op.create_table(
        "telegram_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("messages_processed", sa.Integer(), nullable=False),
        sa.Column("candidates_created", sa.Integer(), nullable=False),
        sa.Column("error_log", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["telegram_sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_sync_runs_source_id",
        "telegram_sync_runs",
        ["source_id"],
        unique=False,
    )

    op.create_table(
        "telegram_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("author_id", sa.BigInteger(), nullable=True),
        sa.Column("author_name", sa.String(length=512), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("message_link", sa.String(length=1024), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=False),
        sa.Column("is_resume_candidate", sa.Boolean(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["telegram_sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_messages_source_id",
        "telegram_messages",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        "uq_telegram_messages_source_tgmsg",
        "telegram_messages",
        ["source_id", "telegram_message_id"],
        unique=True,
    )

    op.create_table(
        "telegram_message_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.String(length=1024), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["telegram_messages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_telegram_message_attachments_message_id",
        "telegram_message_attachments",
        ["message_id"],
        unique=False,
    )
