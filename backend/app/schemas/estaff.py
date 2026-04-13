from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.search import LLMAnalysisOut

# Максимум кандидатов в одном запросе выгрузки и в запросе пакетного статуса.
MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS = 50
MAX_ESTAFF_EXPORT_BATCH_CANDIDATE_IDS = MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS


class EstaffCredentialsIn(BaseModel):
    server_name: str = Field(min_length=1, max_length=200)
    api_token: str = Field(min_length=1, max_length=2000)


class EstaffCredentialsStatusOut(BaseModel):
    configured: bool


class EstaffCredentialsPutOut(BaseModel):
    status: str = "saved"


class EstaffVacancyItemOut(BaseModel):
    id: str
    title: str
    subtitle: str | None = None


class EstaffVacanciesListOut(BaseModel):
    items: list[EstaffVacancyItemOut]


class EstaffExportItemIn(BaseModel):
    candidate_id: str | None = Field(
        default=None,
        max_length=128,
        description="Внутренний идентификатор кандидата: UUID профиля (Telegram) или id резюме HeadHunter.",
    )
    hh_resume_id: str | None = Field(
        default=None,
        max_length=128,
        description="Устарело: то же значение, что candidate_id для кандидатов HeadHunter.",
    )
    candidate: dict[str, Any] | None = Field(
        default=None,
        description="Резерв: готовый объект candidate. Основной сценарий — сбор на сервере из HH; справочники не разрешаются.",
    )
    vacancy_id: str = Field(min_length=1, max_length=256)
    include_hr_llm_bundle: bool = False
    hr_llm_summary: str | None = Field(
        default=None,
        description="Сводка ИИ с клиента; если не задана, при include_hr_llm_bundle подставляется из избранного.",
    )
    hr_llm_score: int | None = Field(
        default=None,
        description="Балл ИИ с клиента; если не задан, при include_hr_llm_bundle подставляется из избранного.",
    )
    hr_llm_analysis: LLMAnalysisOut | None = Field(
        default=None,
        description="Полная структура оценки ИИ (балл, релевантность, списки, вывод); приоритетнее полей hr_llm_summary/hr_llm_score.",
    )
    hr_search_query: str | None = Field(
        default=None,
        max_length=2000,
        description="Поисковый запрос для параметра q в ссылке на карточку кандидата.",
    )

    @model_validator(mode="after")
    def _require_candidate_identifier(self) -> EstaffExportItemIn:
        cid = (self.candidate_id or "").strip()
        hid = (self.hh_resume_id or "").strip()
        if not cid and not hid:
            raise ValueError(
                "Укажите candidate_id (предпочтительно) или устаревшее поле hh_resume_id",
            )
        return self

    def effective_candidate_id(self) -> str:
        return (self.candidate_id or "").strip() or (self.hh_resume_id or "").strip()


class EstaffExportRequestIn(BaseModel):
    user_login: str = Field(min_length=1, max_length=256)
    items: list[EstaffExportItemIn] = Field(min_length=1)


class EstaffUserCheckRequestIn(BaseModel):
    login: str = Field(min_length=1, max_length=256)


class EstaffUserCheckOut(BaseModel):
    valid: bool
    login: str
    user_name: str | None = None


class EstaffExportResultOut(BaseModel):
    export_id: str
    candidate_id: str
    hh_resume_id: str | None = Field(
        default=None,
        description="Для HeadHunter совпадает с candidate_id; для Telegram пусто (совместимость поля).",
    )
    status: str
    estaff_candidate_id: str | None = None
    estaff_vacancy_id: str | None = None
    error_message: str | None = None
    error_stage: str | None = None
    preparation_warnings: list[str] | None = None
    exported_at: datetime | None = None
    created_at: datetime | None = None


class EstaffExportBatchOut(BaseModel):
    results: list[EstaffExportResultOut]


class EstaffExportRowOut(BaseModel):
    id: str
    candidate_id: str
    hh_resume_id: str | None = None
    estaff_candidate_id: str | None = None
    estaff_vacancy_id: str | None = None
    status: str
    error_message: str | None = None
    error_stage: str | None = None
    preparation_warnings: list[str] | None = None
    exported_at: datetime | None = None
    created_at: datetime


class EstaffExportsListOut(BaseModel):
    items: list[EstaffExportRowOut]
    total: int
    page: int
    per_page: int


class EstaffExportLatestOut(BaseModel):
    found: bool
    export_id: str | None = None
    candidate_id: str | None = None
    hh_resume_id: str | None = None
    status: str | None = None
    estaff_candidate_id: str | None = None
    error_message: str | None = None
    error_stage: str | None = None
    preparation_warnings: list[str] | None = None
    exported_at: datetime | None = None
    created_at: datetime | None = None


def _normalize_export_id_list(raw: Any, *, field_label: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError(f"{field_label} должен быть массивом строк")
    seen: set[str] = set()
    out: list[str] = []
    for x in raw:
        s = str(x).strip()
        if not s or len(s) > 128:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


class EstaffExportLatestBatchIn(BaseModel):
    candidate_ids: list[str] = Field(default_factory=list)
    hh_resume_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _legacy_body(cls, data: Any) -> Any:
        if data is None:
            return {"candidate_ids": [], "hh_resume_ids": []}
        if isinstance(data, list):
            return {"candidate_ids": [], "hh_resume_ids": data}
        if not isinstance(data, dict):
            raise TypeError(
                "Тело запроса должно быть объектом с полями candidate_ids и/или hh_resume_ids",
            )
        return data

    @model_validator(mode="after")
    def _merge_and_cap(self) -> EstaffExportLatestBatchIn:
        c = _normalize_export_id_list(self.candidate_ids, field_label="candidate_ids")
        h = _normalize_export_id_list(self.hh_resume_ids, field_label="hh_resume_ids")
        seen: set[str] = set()
        merged: list[str] = []
        for s in c + h:
            if s in seen:
                continue
            seen.add(s)
            merged.append(s)
        if len(merged) > MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS:
            raise ValueError(
                f"Не более {MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS} идентификаторов",
            )
        self.candidate_ids = merged
        self.hh_resume_ids = []
        return self


class EstaffExportLatestBatchItemOut(BaseModel):
    candidate_id: str
    hh_resume_id: str | None = None
    found: bool
    export_id: str | None = None
    status: str | None = None
    estaff_candidate_id: str | None = None
    error_message: str | None = None
    error_stage: str | None = None
    preparation_warnings: list[str] | None = None
    exported_at: datetime | None = None
    created_at: datetime | None = None


class EstaffExportLatestBatchOut(BaseModel):
    items: list[EstaffExportLatestBatchItemOut]
