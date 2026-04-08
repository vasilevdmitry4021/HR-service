from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import mapped_column, relationship

from app.db.base import Base


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = mapped_column(String(32), nullable=False, index=True)
    source_resume_id = mapped_column(String(256), nullable=False)
    source_url = mapped_column(String(1024), nullable=True)
    full_name = mapped_column(String(512), nullable=True)
    title = mapped_column(String(512), nullable=True)
    area = mapped_column(String(256), nullable=True)
    experience_years = mapped_column(Integer, nullable=True)
    skills = mapped_column(JSONB, nullable=True)
    salary_amount = mapped_column(Integer, nullable=True)
    salary_currency = mapped_column(String(16), nullable=True)
    contacts = mapped_column(JSONB, nullable=True)
    about = mapped_column(Text, nullable=True)
    education = mapped_column(JSONB, nullable=True)
    work_experience = mapped_column(JSONB, nullable=True)
    raw_text = mapped_column(Text, nullable=True)
    normalized_payload = mapped_column(JSONB, nullable=True)
    parse_confidence = mapped_column(Float, nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    contact_rows = relationship(
        "CandidateContact", back_populates="candidate", cascade="all, delete-orphan"
    )
    source_links = relationship(
        "CandidateSourceLink", back_populates="candidate", cascade="all, delete-orphan"
    )


class CandidateContact(Base):
    __tablename__ = "candidate_contacts"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    contact_type = mapped_column(String(32), nullable=False)
    contact_value = mapped_column(String(512), nullable=False)
    is_verified = mapped_column(Boolean, nullable=False, default=False)

    candidate = relationship("CandidateProfile", back_populates="contact_rows")


class CandidateSourceLink(Base):
    __tablename__ = "candidate_source_links"

    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("candidate_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = mapped_column(String(32), nullable=False)
    source_id = mapped_column(String(256), nullable=False)
    source_url = mapped_column(String(1024), nullable=True)
    created_at = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate = relationship("CandidateProfile", back_populates="source_links")
