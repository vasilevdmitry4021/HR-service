"""Telegram ingestion tables, candidate_profiles, favorites.candidate_id

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "candidate_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_resume_id", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("full_name", sa.String(length=512), nullable=True),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("area", sa.String(length=256), nullable=True),
        sa.Column("experience_years", sa.Integer(), nullable=True),
        sa.Column("skills", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("salary_amount", sa.Integer(), nullable=True),
        sa.Column("salary_currency", sa.String(length=16), nullable=True),
        sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("education", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("work_experience", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("normalized_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("parse_confidence", sa.Float(), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_profiles_source_type",
        "candidate_profiles",
        ["source_type"],
        unique=False,
    )

    op.create_table(
        "candidate_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_type", sa.String(length=32), nullable=False),
        sa.Column("contact_value", sa.String(length=512), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_contacts_candidate_id",
        "candidate_contacts",
        ["candidate_id"],
        unique=False,
    )

    op.create_table(
        "candidate_source_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=256), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["candidate_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_candidate_source_links_candidate_id",
        "candidate_source_links",
        ["candidate_id"],
        unique=False,
    )

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

    op.drop_constraint("uq_favorites_user_resume", "favorites", type_="unique")
    op.add_column(
        "favorites",
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_favorites_candidate_id",
        "favorites",
        "candidate_profiles",
        ["candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_favorites_candidate_id",
        "favorites",
        ["candidate_id"],
        unique=False,
    )
    op.alter_column(
        "favorites",
        "hh_resume_id",
        existing_type=sa.String(length=128),
        nullable=True,
    )
    op.create_index(
        "uq_favorites_user_hh_resume",
        "favorites",
        ["user_id", "hh_resume_id"],
        unique=True,
        postgresql_where=sa.text("hh_resume_id IS NOT NULL"),
    )
    op.create_index(
        "uq_favorites_user_candidate",
        "favorites",
        ["user_id", "candidate_id"],
        unique=True,
        postgresql_where=sa.text("candidate_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_favorites_user_candidate", table_name="favorites")
    op.drop_index("uq_favorites_user_hh_resume", table_name="favorites")
    op.alter_column(
        "favorites",
        "hh_resume_id",
        existing_type=sa.String(length=128),
        nullable=False,
    )
    op.drop_index("ix_favorites_candidate_id", table_name="favorites")
    op.drop_constraint("fk_favorites_candidate_id", "favorites", type_="foreignkey")
    op.drop_column("favorites", "candidate_id")
    op.create_unique_constraint(
        "uq_favorites_user_resume",
        "favorites",
        ["user_id", "hh_resume_id"],
    )

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

    op.drop_index(
        "ix_candidate_source_links_candidate_id",
        table_name="candidate_source_links",
    )
    op.drop_table("candidate_source_links")

    op.drop_index("ix_candidate_contacts_candidate_id", table_name="candidate_contacts")
    op.drop_table("candidate_contacts")

    op.drop_index("ix_candidate_profiles_source_type", table_name="candidate_profiles")
    op.drop_table("candidate_profiles")
