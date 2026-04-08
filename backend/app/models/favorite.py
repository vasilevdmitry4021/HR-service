from __future__ import annotations

import uuid

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hh_resume_id = Column(String(128), nullable=True)
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title_snapshot = Column(String(512), nullable=True)
    full_name = Column(String(256), nullable=True)
    area = Column(String(256), nullable=True)
    skills_snapshot = Column(JSONB, nullable=True)
    experience_years = Column(Integer, nullable=True)
    age = Column(Integer, nullable=True)
    salary_amount = Column(Integer, nullable=True)
    salary_currency = Column(String(16), nullable=True)
    llm_score = Column(Integer, nullable=True)
    llm_summary = Column(Text(), nullable=True)
    notes = Column(Text(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="favorites")
    candidate = relationship("CandidateProfile", foreign_keys=[candidate_id])
