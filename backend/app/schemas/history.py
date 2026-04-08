from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SearchHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    query: str
    filters: dict[str, Any] | None
    parsed_params: dict[str, Any]
    page: int
    per_page: int
    found: int
    created_at: datetime


class SearchHistoryListOut(BaseModel):
    items: list[SearchHistoryOut]
    total: int
