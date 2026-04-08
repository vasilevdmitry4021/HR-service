from __future__ import annotations

import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column, relationship

from app.db.base import Base


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_id = mapped_column(String(64), nullable=False)
    encrypted_api_hash = mapped_column(LargeBinary, nullable=False)
    encrypted_session = mapped_column(LargeBinary, nullable=True)
    phone_hint = mapped_column(String(32), nullable=True)
    auth_status = mapped_column(String(32), nullable=False, index=True)
    pending_auth = mapped_column(JSONB, nullable=True)
    last_sync_at = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User", back_populates="telegram_accounts")
    sources = relationship(
        "TelegramSource", back_populates="account", cascade="all, delete-orphan"
    )


class TelegramSource(Base):
    __tablename__ = "telegram_sources"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_id = mapped_column(BigInteger, nullable=False)
    link = mapped_column(String(1024), nullable=False)
    type = mapped_column(String(32), nullable=False)
    display_name = mapped_column(String(512), nullable=False)
    access_status = mapped_column(String(32), nullable=False)
    is_enabled = mapped_column(Boolean, nullable=False, default=True)
    last_message_id = mapped_column(BigInteger, nullable=True)
    last_check_at = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at = mapped_column(DateTime(timezone=True), nullable=True)
    error_message = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    account = relationship("TelegramAccount", back_populates="sources")
    sync_runs = relationship(
        "TelegramSyncRun", back_populates="source", cascade="all, delete-orphan"
    )
    messages = relationship(
        "TelegramMessage", back_populates="source", cascade="all, delete-orphan"
    )


class TelegramSyncRun(Base):
    __tablename__ = "telegram_sync_runs"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = mapped_column(String(32), nullable=False)
    started_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)
    messages_processed = mapped_column(Integer, nullable=False, default=0)
    candidates_created = mapped_column(Integer, nullable=False, default=0)
    error_log = mapped_column(JSONB, nullable=True)

    source = relationship("TelegramSource", back_populates="sync_runs")


class TelegramMessage(Base):
    __tablename__ = "telegram_messages"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    telegram_message_id = mapped_column(BigInteger, nullable=False)
    published_at = mapped_column(DateTime(timezone=True), nullable=True)
    author_id = mapped_column(BigInteger, nullable=True)
    author_name = mapped_column(String(512), nullable=True)
    text = mapped_column(Text, nullable=True)
    message_link = mapped_column(String(1024), nullable=True)
    content_hash = mapped_column(String(128), nullable=True)
    parse_status = mapped_column(String(32), nullable=False)
    is_resume_candidate = mapped_column(Boolean, nullable=False, default=False)
    confidence_score = mapped_column(Float, nullable=True)
    parse_error = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    source = relationship("TelegramSource", back_populates="messages")
    attachments = relationship(
        "TelegramMessageAttachment",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class TelegramMessageAttachment(Base):
    __tablename__ = "telegram_message_attachments"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("telegram_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_type = mapped_column(String(32), nullable=False)
    file_path = mapped_column(String(1024), nullable=False)
    file_hash = mapped_column(String(128), nullable=True)
    extracted_text = mapped_column(Text, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message = relationship("TelegramMessage", back_populates="attachments")
