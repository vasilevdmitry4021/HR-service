from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RequestLog(Base):
    __tablename__ = "request_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    query_id = mapped_column(String(64), nullable=True, index=True)

    user_id = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    user_email = mapped_column(String(320), nullable=True)

    method: Mapped[str] = mapped_column(String(10), nullable=False)
    route: Mapped[str] = mapped_column(String(256), nullable=False)
    route_tag: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    request_body_summary: Mapped[Any] = mapped_column(JSONB, nullable=True)
    response_summary: Mapped[Any] = mapped_column(JSONB, nullable=True)
    search_metrics: Mapped[Any] = mapped_column(JSONB, nullable=True)
    integration_calls: Mapped[Any] = mapped_column(JSONB, nullable=True)

    error_type = mapped_column(String(128), nullable=True, index=True)
    error_message = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_request_log_created_at_route_tag", "created_at", "route_tag"),
    )
