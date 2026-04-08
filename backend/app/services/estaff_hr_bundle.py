"""HTML-вложение со ссылкой на карточку HR и сводкой ИИ для выгрузки в e-staff."""

from __future__ import annotations

import html
import uuid
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.favorite import Favorite


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


def resolve_hr_llm_fields_for_bundle(
    *,
    client_summary: str | None,
    client_score: int | None,
    favorite: Favorite | None,
) -> tuple[str | None, int | None]:
    """Берёт сводку и балл с клиента; пустые поля добирает из записи избранного."""
    summary: str | None = None
    if client_summary is not None:
        summary = client_summary.strip() or None
    if summary is None and favorite and favorite.llm_summary:
        summary = str(favorite.llm_summary).strip() or None

    score: int | None = None
    if client_score is not None:
        score = int(client_score)
    if score is None and favorite is not None and favorite.llm_score is not None:
        score = int(favorite.llm_score)

    return summary, score


def build_hr_llm_bundle_attachment(
    *,
    settings: Settings,
    cand_key: str,
    summary: str | None,
    score: int | None,
    search_query: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    type_id = (settings.estaff_hr_bundle_attachment_type_id or "").strip()
    if not type_id:
        warnings.append(
            "Не задан тип вложения e-staff для блока HR (ESTAFF_HR_BUNDLE_ATTACHMENT_TYPE_ID); вложение не добавлено.",
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

    has_summary = bool(summary)
    has_score = score is not None

    if not has_summary and not has_score:
        warnings.append(
            "Нет данных ИИ для вложения (сводка и балл не заполнены); вложение не добавлено.",
        )
        return None, warnings

    parts: list[str] = [
        "<h3>Ссылка на резюме в HR-сервисе</h3>",
        f'<p><a href="{html.escape(href, quote=True)}">Открыть карточку кандидата</a></p>',
    ]
    if has_score:
        parts.append("<h3>Оценка ИИ</h3>")
        parts.append(f"<p>{html.escape(str(score), quote=False)}</p>")
    if has_summary and summary is not None:
        parts.append("<h3>Сводка</h3>")
        parts.append(f"<p>{html.escape(summary, quote=False)}</p>")

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
    client_summary: str | None,
    client_score: int | None,
    search_query: str | None,
    settings: Settings,
) -> tuple[dict[str, Any] | None, list[str]]:
    if not include_bundle:
        return None, []
    fav = find_favorite_for_estaff_bundle(db, user_id, cand_key)
    summary, score = resolve_hr_llm_fields_for_bundle(
        client_summary=client_summary,
        client_score=client_score,
        favorite=fav,
    )
    return build_hr_llm_bundle_attachment(
        settings=settings,
        cand_key=cand_key,
        summary=summary,
        score=score,
        search_query=search_query,
    )
