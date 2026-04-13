"""HTML-вложение со ссылкой на карточку HR и полной оценкой ИИ для выгрузки в e-staff."""

from __future__ import annotations

import html
import uuid
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.favorite import Favorite
from app.schemas.search import LLMAnalysisOut


def find_favorite_for_estaff_bundle(
    db: Session,
    user_id: uuid.UUID,
    cand_key: str,
) -> Favorite | None:
    ck = (cand_key or "").strip()
    if not ck:
        return None
    clauses = [Favorite.hh_resume_id == ck]
    try:
        prof_id = uuid.UUID(ck)
        clauses.append(Favorite.candidate_id == prof_id)
    except ValueError:
        pass
    stmt = (
        select(Favorite)
        .where(Favorite.user_id == user_id)
        .where(or_(*clauses))
    )
    return db.scalars(stmt).first()


def _llm_analysis_has_substance(out: LLMAnalysisOut) -> bool:
    if out.llm_score is not None:
        return True
    if out.is_relevant is not None:
        return True
    if out.strengths:
        return True
    if out.gaps:
        return True
    if isinstance(out.summary, str) and out.summary.strip():
        return True
    return False


def _favorite_to_llm_analysis(favorite: Favorite | None) -> LLMAnalysisOut | None:
    if favorite is None:
        return None
    raw = favorite.llm_analysis
    if isinstance(raw, dict) and raw:
        try:
            out = LLMAnalysisOut.model_validate(raw)
        except Exception:
            out = None
        else:
            if _llm_analysis_has_substance(out):
                return out
    summary_raw = favorite.llm_summary
    summary = summary_raw.strip() if isinstance(summary_raw, str) else None
    if summary == "":
        summary = None
    score = favorite.llm_score
    if score is None and summary is None:
        return None
    return LLMAnalysisOut(
        llm_score=score,
        is_relevant=None,
        strengths=[],
        gaps=[],
        summary=summary,
    )


def merge_llm_analysis_for_estaff_bundle(
    *,
    favorite: Favorite | None,
    client_analysis: LLMAnalysisOut | None,
    client_summary: str | None,
    client_score: int | None,
) -> LLMAnalysisOut | None:
    """Собирает итоговую оценку: избранное как база, полный объект с клиента приоритетнее, затем поля hr_llm_summary / hr_llm_score."""
    base = _favorite_to_llm_analysis(favorite)
    if client_analysis is not None and _llm_analysis_has_substance(client_analysis):
        merged = client_analysis.model_copy(deep=True)
    else:
        merged = base.model_copy(deep=True) if base is not None else None

    if client_summary is not None:
        s = client_summary.strip() if isinstance(client_summary, str) else None
        summary_val = s if s else None
        if merged is None:
            merged = LLMAnalysisOut(summary=summary_val)
        else:
            merged.summary = summary_val

    if client_score is not None:
        if merged is None:
            merged = LLMAnalysisOut(llm_score=int(client_score))
        else:
            merged.llm_score = int(client_score)

    if merged is None or not _llm_analysis_has_substance(merged):
        return None
    return merged


def build_hr_llm_bundle_attachment(
    *,
    settings: Settings,
    cand_key: str,
    analysis: LLMAnalysisOut,
    search_query: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    type_id = (settings.estaff_hr_bundle_attachment_type_id or "").strip()
    if not type_id:
        warnings.append(
            "Не задан тип вложения e-staff для блока HR (ESTAFF_HR_BUNDLE_ATTACHMENT_TYPE_ID); вложение не добавлено.",
        )
        return None, warnings

    if not _llm_analysis_has_substance(analysis):
        warnings.append(
            "Нет данных ИИ для вложения (сводка и балл не заполнены); вложение не добавлено.",
        )
        return None, warnings

    ck = (cand_key or "").strip()
    enc = quote(ck, safe="")
    rel = f"/candidates/{enc}"
    q = (search_query or "").strip()
    if q:
        rel = f"{rel}?{urlencode({'q': q})}"

    base = (settings.hr_public_base_url or "").strip().rstrip("/")
    if base:
        href = f"{base}{rel}"
    else:
        href = rel
        warnings.append(
            "Не задан публичный URL фронтенда (HR_PUBLIC_BASE_URL); в ссылке только относительный путь.",
        )

    parts: list[str] = [
        "<h3>Ссылка на резюме в HR-сервисе</h3>",
        f'<p><a href="{html.escape(href, quote=True)}">Открыть карточку кандидата</a></p>',
    ]

    if analysis.llm_score is not None:
        parts.append("<h3>Оценка ИИ</h3>")
        parts.append(
            f"<p>{html.escape(str(analysis.llm_score), quote=False)}</p>",
        )

    if analysis.is_relevant is not None:
        parts.append("<h3>Релевантность</h3>")
        rel_text = (
            "По мнению модели кандидат релевантен запросу"
            if analysis.is_relevant
            else "По мнению модели кандидат не релевантен запросу"
        )
        parts.append(f"<p>{html.escape(rel_text, quote=False)}</p>")

    if analysis.strengths:
        parts.append("<h3>Сильные стороны</h3>")
        parts.append("<ul>")
        for line in analysis.strengths:
            t = str(line).strip()
            if t:
                parts.append(f"<li>{html.escape(t, quote=False)}</li>")
        parts.append("</ul>")

    if analysis.gaps:
        parts.append("<h3>Пробелы и риски</h3>")
        parts.append("<ul>")
        for line in analysis.gaps:
            t = str(line).strip()
            if t:
                parts.append(f"<li>{html.escape(t, quote=False)}</li>")
        parts.append("</ul>")

    if isinstance(analysis.summary, str) and analysis.summary.strip():
        parts.append("<h3>Вывод</h3>")
        parts.append(
            f"<p>{html.escape(analysis.summary.strip(), quote=False)}</p>",
        )

    html_data = "\n".join(parts)
    att: dict[str, Any] = {
        "content_type": "text/html",
        "html_data": html_data,
        "type_id": type_id,
        "file_name": "hr-service-note.html",
    }
    return att, warnings


def prepare_hr_llm_bundle_for_export_item(
    db: Session,
    user_id: uuid.UUID,
    cand_key: str,
    *,
    include_bundle: bool,
    client_analysis: LLMAnalysisOut | None,
    client_summary: str | None,
    client_score: int | None,
    search_query: str | None,
    settings: Settings,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not include_bundle:
        return None, []
    fav = find_favorite_for_estaff_bundle(db, user_id, cand_key)
    merged = merge_llm_analysis_for_estaff_bundle(
        favorite=fav,
        client_analysis=client_analysis,
        client_summary=client_summary,
        client_score=client_score,
    )
    if merged is None:
        return None, [
            "Нет данных ИИ для вложения (сводка и балл не заполнены); вложение не добавлено.",
        ]
    return build_hr_llm_bundle_attachment(
        settings=settings,
        cand_key=cand_key,
        analysis=merged,
        search_query=search_query,
    )
