from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ExperienceBucket = Literal["noExperience", "between1And3", "between3And6", "moreThan6"]

RelocationKind = Literal["living", "living_but_relocation"]


class ResumeSearchFilters(BaseModel):
    """Явные фильтры поиска резюме (HH API + внутренняя валидация)."""

    model_config = ConfigDict(extra="ignore")

    area: int | None = Field(default=None, description="ID региона HH (например 1 — Москва)")
    professional_role: int | None = None
    industry: int | None = None
    skill: list[int] | None = None
    experience: ExperienceBucket | None = None
    gender: Literal["male", "female"] | None = None
    age_from: int | None = Field(default=None, ge=14, le=100)
    age_to: int | None = Field(default=None, ge=14, le=100)
    salary_from: int | None = Field(default=None, ge=0)
    salary_to: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    period: int | None = Field(default=None, ge=1, description="Период обновления резюме, дней")
    relocation: RelocationKind | None = None
    education_level: str | None = Field(default=None, max_length=64)
    employment: list[str] | None = None
