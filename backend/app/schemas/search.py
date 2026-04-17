from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.search_filters import ResumeSearchFilters


class SearchParseIn(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    force_reparse: bool = False


class SearchParseOut(BaseModel):
    parsed_params: dict[str, Any]
    confidence: float
    processing_time_ms: int


class LLMAnalysisOut(BaseModel):
    llm_score: int | None = None
    is_relevant: bool | None = None
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    summary: str | None = None


class WorkExperienceItemOut(BaseModel):
    """Место работы в резюме (детальная карточка; в поиске не отдаётся)."""

    company: str = ""
    position: str = ""
    start: str | None = None
    end: str | None = None
    period_label: str | None = None
    area: str | None = None
    industry: str | None = None
    description: str | None = None


class EducationItemOut(BaseModel):
    """Запись об образовании (детальная карточка)."""

    level: str | None = None
    organization: str | None = None
    speciality: str | None = None
    year: str | None = None
    summary: str | None = None


class CandidateOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    hh_resume_id: str = ""
    hh_resume_url: str | None = None
    source_type: Literal["hh"] = "hh"
    candidate_profile_id: str | None = None
    source_resume_id: str | None = Field(
        default=None,
        description="Внешний идентификатор в контуре источника.",
    )
    title: str
    full_name: str
    age: int | None = None
    experience_years: int | None = None
    salary: dict[str, Any] | None = None
    skills: list[str]
    area: str
    llm_score: int | None = None
    llm_analysis: LLMAnalysisOut | None = None
    parse_confidence: float | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    incompleteness_flags: list[str] = Field(default_factory=list)


class CandidateDetailOut(CandidateOut):
    favorite_id: str | None = None
    favorite_notes: str | None = None
    work_experience: list[WorkExperienceItemOut] = Field(default_factory=list)
    about: str | None = None
    education: list[EducationItemOut] = Field(default_factory=list)


class SearchIn(BaseModel):
    query: str = Field(default="", max_length=4000)
    source_scope: Literal["hh"] = "hh"
    sort_by: Literal[
        "server",
        "llm_desc",
        "llm_score_desc",
        "experience_desc",
        "experience_asc",
    ] = "server"
    filters: ResumeSearchFilters | None = None
    page: int = Field(default=0, ge=0)
    per_page: int = Field(default=20, ge=1, le=50)
    snapshot_id: str | None = None


class SearchOut(BaseModel):
    items: list[CandidateOut]
    found: int
    page: int
    pages: int
    per_page: int
    parsed_params: dict[str, Any]
    snapshot_id: str | None = None
    found_raw_hh: int | None = None
    source_scope: Literal["hh"] = "hh"


class EvaluateIn(BaseModel):
    """Запрос на оценку резюме из снимка."""

    pass


class EvaluateCandidateOut(BaseModel):
    """Ответ POST .../evaluate: идентификатор резюме и числовой балл (без карточки и навыков)."""

    model_config = ConfigDict(extra="ignore")

    id: str
    llm_score: int | None = None


class EvaluateOut(BaseModel):
    items: list[EvaluateCandidateOut]
    evaluated_count: int
    llm_scored_count: int = 0
    fallback_scored_count: int = 0
    coverage_ratio: float = 0.0
    processing_time_seconds: float
    metrics: dict[str, Any] = Field(default_factory=dict)


class EvaluateStartOut(BaseModel):
    job_id: str
    status: str
    total_count: int


class EvaluateProgressOut(BaseModel):
    job_id: str
    status: str
    stage: str
    phase: str = "interactive"
    total_count: int
    scored_count: int
    llm_scored_count: int = 0
    fallback_scored_count: int = 0
    coverage_ratio: float = 0.0
    completed_count: int
    interactive_total_count: int = 0
    background_total_count: int = 0
    interactive_done_count: int = 0
    background_done_count: int = 0
    interactive_llm_scored_count: int = 0
    background_llm_scored_count: int = 0
    interactive_fallback_count: int = 0
    background_fallback_count: int = 0
    items: list[EvaluateCandidateOut]
    processing_time_seconds: float | None = None
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class AnalyzeIn(BaseModel):
    top_n: int = Field(default=15, ge=1, le=50)


class AnalyzeOut(BaseModel):
    items: list[CandidateOut]
    analyzed_count: int
    processing_time_seconds: float


class AnalyzeStartOut(BaseModel):
    job_id: str
    status: str
    total_count: int


class AnalyzeProgressOut(BaseModel):
    job_id: str
    status: str
    stage: str
    total_count: int
    processed_count: int
    analyzed_count: int
    analyses: dict[str, Any] = {}
    processing_time_seconds: float | None = None
    error: str | None = None
