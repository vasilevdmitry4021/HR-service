from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class FavoriteCreateIn(BaseModel):
    hh_resume_id: str = Field(default="", max_length=128)
    candidate_profile_id: uuid.UUID | None = None
    title_snapshot: str | None = Field(default=None, max_length=512)
    full_name: str | None = Field(default=None, max_length=256)
    area: str | None = Field(default=None, max_length=256)
    skills_snapshot: list[str] | None = None
    experience_years: int | None = None
    age: int | None = None
    salary_amount: int | None = None
    salary_currency: str | None = Field(default=None, max_length=16)
    # Обязательны в теле запроса; значение null — если оценка ИИ не выполнялась
    llm_score: int | None
    llm_summary: str | None
    notes: str = Field(default="", max_length=8000)

    @model_validator(mode="after")
    def _require_ref(self) -> "FavoriteCreateIn":
        h = (self.hh_resume_id or "").strip()
        if not h and self.candidate_profile_id is None:
            raise ValueError("Укажите hh_resume_id или candidate_profile_id")
        return self


class FavoriteNotesPatch(BaseModel):
    notes: str = Field(max_length=8000)


class FavoriteOut(BaseModel):
    id: uuid.UUID
    hh_resume_id: str | None = None
    candidate_id: uuid.UUID | None = None
    title_snapshot: str | None
    full_name: str | None
    area: str | None
    skills_snapshot: list[str] | None
    experience_years: int | None
    age: int | None
    salary_amount: int | None
    salary_currency: str | None
    llm_score: int | None
    llm_summary: str | None
    notes: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
