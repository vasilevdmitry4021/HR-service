from __future__ import annotations

import enum
import uuid

from sqlalchemy import Column, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base import Base


class EstaffExportStatus(str, enum.Enum):
    pending = "pending"
    success = "success"
    error = "error"


class EstaffExport(Base):
    __tablename__ = "estaff_exports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    hh_resume_id = Column(String(128), nullable=False, index=True)
    estaff_candidate_id = Column(String(256), nullable=True)
    estaff_vacancy_id = Column(String(256), nullable=True)
    status = Column(String(32), nullable=False)
    error_message = Column(Text, nullable=True)
    export_detail = Column(JSON, nullable=True)
    exported_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    user = relationship("User", back_populates="estaff_exports")
