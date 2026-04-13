from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_super_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    can_edit_integration_settings: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    # Идентификатор из JWT refresh; при выдаче новой пары предыдущий refresh становится недействительным
    active_refresh_jti = mapped_column(String(64), nullable=True)

    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete-orphan")
    search_history = relationship(
        "SearchHistory", back_populates="user", cascade="all, delete-orphan"
    )
    search_templates = relationship(
        "SearchTemplate", back_populates="user", cascade="all, delete-orphan"
    )
    estaff_exports = relationship(
        "EstaffExport", back_populates="user", cascade="all, delete-orphan"
    )
    telegram_accounts = relationship(
        "TelegramAccount", back_populates="owner", cascade="all, delete-orphan"
    )
    oauth_identities = relationship(
        "OAuthIdentity", back_populates="user", cascade="all, delete-orphan"
    )
