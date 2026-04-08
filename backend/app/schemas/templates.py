from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.search_filters import ResumeSearchFilters


class SearchTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    query: str
    filters: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime


class SearchTemplateCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=4000)
    filters: ResumeSearchFilters | None = None


class SearchTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    query: str | None = Field(default=None, min_length=1, max_length=4000)
    filters: ResumeSearchFilters | None = None
