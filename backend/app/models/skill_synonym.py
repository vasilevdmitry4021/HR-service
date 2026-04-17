from __future__ import annotations

import uuid
from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column

from app.db.base import Base


class SkillSynonym(Base):
    __tablename__ = "skill_synonyms"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_norm = mapped_column(String(128), unique=True, index=True, nullable=False)
    canonical = mapped_column(String(128), nullable=False)
    synonyms_json = mapped_column(JSONB, nullable=False, default=list)
    source = mapped_column(String(16), nullable=False, default="llm")
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    expires_at = mapped_column(DateTime(timezone=True), nullable=True)
