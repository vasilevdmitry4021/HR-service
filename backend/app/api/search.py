from __future__ import annotations

import logging
import math
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_search_parse_debug_access
from app.api.hh_access import ensure_hh_access_token
from app.config import settings
from app.models.search_history import SearchHistory
from app.models.user import User
from app.schemas.search import (
    AnalyzeIn,
    AnalyzeOut,
    CandidateOut,
    EvaluateCandidateOut,
    EvaluateIn,
    EvaluateOut,
    SearchIn,
    SearchOut,
    SearchParseIn,
    SearchParseOut,
)
from app.services import hh_client
from app.services import llm_client
from app.services import llm_evaluation
from app.services import nlp_service
from app.services import post_filter
from app.services import telegram_search
from app.services.hh_client import HHClientError
from app.services.search_snapshot_cache import (
    SearchSnapshotData,
    get_snapshot,
    replace_snapshot,
    save_snapshot,
)

router = APIRouter(prefix="/search", tags=["search"])

logger = logging.getLogger(__name__)


def _evaluate_response_item_dict(row: dict[str, Any]) -> dict[str, Any]:
    """Тело ответа /evaluate: только id резюме и числовая оценка."""
    rid = str(row.get("id", row.get("hh_resume_id", "")))
    return {
        "id": rid,
        "llm_score": row.get("llm_score"),
    }


def _llm_endpoint_configured(db: Session) -> bool:
    return llm_client.llm_connection_configured(db)


def _candidate_dict_from_raw(r: dict[str, Any]) -> dict[str, Any]:
    rid = str(r.get("id", r.get("hh_resume_id", "")))
    hh_url = r.get("hh_resume_url")
    if hh_url is not None and not isinstance(hh_url, str):
        hh_url = str(hh_url) if hh_url else None
    if isinstance(hh_url, str):
        hh_url = hh_url.strip() or None
    st = r.get("source_type") or "hh"
    if st not in ("hh", "telegram"):
        st = "hh"
    cpid = r.get("candidate_profile_id")
    if cpid is not None:
        cpid = str(cpid).strip() or None
    src_rid = r.get("source_resume_id")
    if src_rid is not None:
        src_rid = str(src_rid).strip() or None
    pw = r.get("parse_warnings")
    parse_warnings = [str(x).strip() for x in pw] if isinstance(pw, list) else []
    inc = r.get("incompleteness_flags")
    incompleteness = (
        [str(x).strip() for x in inc] if isinstance(inc, list) else []
    )
    ts = r.get("telegram_sources")
    telegram_sources = [x for x in ts if isinstance(x, dict)] if isinstance(ts, list) else []
    ta = r.get("telegram_attachments")
    telegram_attachments = (
        [x for x in ta if isinstance(x, dict)] if isinstance(ta, list) else []
    )
    return {
        "id": rid,
        "hh_resume_id": str(r.get("hh_resume_id", "") or ""),
        "hh_resume_url": hh_url,
        "source_type": st,
        "candidate_profile_id": cpid,
        "source_resume_id": src_rid,
        "title": str(r.get("title", "")),
        "full_name": str(r.get("full_name", "")),
        "age": r.get("age"),
        "experience_years": r.get("experience_years"),
        "salary": r.get("salary"),
        "skills": list(r.get("skills") or []),
        "area": str(r.get("area", "")),
        "llm_score": None,
        "llm_analysis": None,
        "raw_text": r.get("raw_text"),
        "normalized_payload": r.get("normalized_payload"),
        "work_experience": r.get("work_experience"),
        "about": r.get("about"),
        "education": r.get("education"),
        "parse_confidence": r.get("parse_confidence"),
        "parse_warnings": parse_warnings,
        "incompleteness_flags": incompleteness,
        "telegram_sources": telegram_sources,
        "telegram_attachments": telegram_attachments,
    }


def _build_search_items(parsed: dict[str, Any], raw_items: list[dict]) -> list[dict[str, Any]]:
    filtered_items = raw_items
    if settings.strict_numeric_filters:
        filtered_items = post_filter.apply_strict_filters(
            list(raw_items),
            parsed,
            mode=settings.strict_filter_mode,
        )
    filtered_items = list(filtered_items)
    filtered_items.sort(key=lambda r: (0 if r.get("strict_match", True) else 1))
    return [_candidate_dict_from_raw(r) for r in filtered_items]


def _merge_hh_telegram(
    hh_rows: list[dict[str, Any]],
    tg_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for r in hh_rows + tg_rows:
        k = str(r.get("id", ""))
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _snapshot_needs_hh_access(items: list[dict[str, Any]]) -> bool:
    return any((x.get("source_type") or "hh") != "telegram" for x in items)


async def _fetch_hh_resume_pages(
    access: str | None,
    parsed: dict[str, Any],
    filters: Any,
    *,
    max_resumes: int,
    per_page: int,
    db: Session | None = None,
    hh_token_user_id: uuid.UUID | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Собирает резюме с HH постранично до исчерпания выдачи или лимита."""
    all_items: list[dict[str, Any]] = []
    hh_found = 0
    page = 0
    page_size = max(1, min(int(per_page), 100))
    cap = max(0, int(max_resumes))

    while len(all_items) < cap:
        chunk, found = await hh_client.search_resumes(
            access,
            parsed,
            filters,
            page,
            page_size,
            db=db,
            hh_token_user_id=hh_token_user_id,
        )
        hh_found = int(found)
        if not chunk:
            break
        room = cap - len(all_items)
        if room <= 0:
            break
        all_items.extend(chunk[:room])
        if len(chunk) < page_size:
            break
        page += 1
        if len(all_items) >= cap:
            break

    return all_items, hh_found, len(all_items)


@router.post("/parse/debug")
def search_parse_debug(
    body: SearchParseIn,
    db: Session = Depends(get_db),
    _user: User = Depends(require_search_parse_debug_access),
):
    """Отладка: сырой ответ LLM (без mock). Включение и права — через настройки сервера."""
    return llm_client.debug_raw_llm_response(body.query, db)


@router.post("/parse", response_model=SearchParseOut)
def search_parse(
    body: SearchParseIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SearchParseOut:
    parsed, confidence, ms = nlp_service.parse_natural_query(
        body.query, force_reparse=body.force_reparse, db=db
    )
    return SearchParseOut(
        parsed_params=parsed,
        confidence=round(confidence, 4),
        processing_time_ms=ms,
    )


@router.post("/{snapshot_id}/evaluate", response_model=EvaluateOut)
async def evaluate_resumes(
    snapshot_id: str,
    body: EvaluateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvaluateOut:
    _ = body
    if not _llm_endpoint_configured(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не настроен доступ к языковой модели (веб-настройки или INTERNAL_LLM_ENDPOINT).",
        )
    uid = str(user.id)
    snap = get_snapshot(uid, snapshot_id)
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Снимок выдачи устарел или не найден.",
        )

    access: str | None = None
    if _snapshot_needs_hh_access(snap.items):
        if not settings.feature_use_mock_hh:
            access = await ensure_hh_access_token(db, user.id)
            if not access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Подключите HeadHunter для загрузки полных резюме",
                )

    parsed = {**snap.parsed_params, "text": snap.query}
    t0 = time.monotonic()
    base_rows = []
    for d in snap.items:
        nd = dict(d)
        nd["llm_score"] = None
        nd["llm_analysis"] = None
        base_rows.append(nd)

    try:
        updated = await llm_evaluation.evaluate_all_resumes(
            access, base_rows, parsed, db, user_id=user.id
        )
    except Exception as exc:
        logger.exception("Ошибка оценки снимка: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не удалось выполнить оценку резюме",
        ) from exc

    elapsed = time.monotonic() - t0
    new_snap = SearchSnapshotData(
        items=updated,
        found_raw_hh=snap.found_raw_hh,
        loaded_from_hh=snap.loaded_from_hh,
        parsed_params=snap.parsed_params,
        query=snap.query,
        filters=snap.filters,
        evaluated=True,
        analyzed=False,
        source_scope=snap.source_scope,
        found_telegram=snap.found_telegram,
    )
    replace_snapshot(uid, snapshot_id, new_snap)

    items_out = [
        EvaluateCandidateOut(**_evaluate_response_item_dict(x)) for x in updated
    ]
    scored = sum(1 for x in updated if isinstance(x.get("llm_score"), int))
    if scored == 0 and updated:
        logger.warning(
            "Оценка снимка завершена без числовых баллов (LLM не вернул score для ни одного резюме), "
            "snapshot_id=%s, count=%s",
            snapshot_id,
            len(updated),
        )
    return EvaluateOut(
        items=items_out,
        evaluated_count=len(updated),
        processing_time_seconds=round(elapsed, 3),
    )


@router.post("/{snapshot_id}/analyze", response_model=AnalyzeOut)
async def analyze_resumes(
    snapshot_id: str,
    body: AnalyzeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalyzeOut:
    if not _llm_endpoint_configured(db):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не настроен доступ к языковой модели (веб-настройки или INTERNAL_LLM_ENDPOINT).",
        )
    uid = str(user.id)
    snap = get_snapshot(uid, snapshot_id)
    if snap is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Снимок выдачи устарел или не найден.",
        )
    if not any(isinstance(x.get("llm_score"), int) for x in snap.items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала выполните оценку выдачи (evaluate).",
        )

    access: str | None = None
    if _snapshot_needs_hh_access(snap.items):
        if not settings.feature_use_mock_hh:
            access = await ensure_hh_access_token(db, user.id)
            if not access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Подключите HeadHunter для загрузки полных резюме",
                )

    parsed = {**snap.parsed_params, "text": snap.query}
    top_n = body.top_n
    t0 = time.monotonic()
    try:
        updated = await llm_evaluation.analyze_top_resumes(
            access,
            list(snap.items),
            parsed,
            user_id=uid,
            query=snap.query,
            top_n=top_n,
            db=db,
        )
    except Exception as exc:
        logger.exception("Ошибка детального анализа: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не удалось выполнить детальный анализ",
        ) from exc

    elapsed = time.monotonic() - t0
    analyzed_n = sum(1 for x in updated if x.get("llm_analysis"))
    new_snap = SearchSnapshotData(
        items=updated,
        found_raw_hh=snap.found_raw_hh,
        loaded_from_hh=snap.loaded_from_hh,
        parsed_params=snap.parsed_params,
        query=snap.query,
        filters=snap.filters,
        evaluated=True,
        analyzed=True,
        source_scope=snap.source_scope,
        found_telegram=snap.found_telegram,
    )
    replace_snapshot(uid, snapshot_id, new_snap)

    items_out = [CandidateOut(**x) for x in updated]
    return AnalyzeOut(
        items=items_out,
        analyzed_count=analyzed_n,
        processing_time_seconds=round(elapsed, 3),
    )


@router.post("", response_model=SearchOut)
async def search(
    body: SearchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SearchOut:
    uid = str(user.id)
    parsed, _conf, _ms = nlp_service.parse_natural_query(body.query, db=db)
    parsed = {**parsed, "text": body.query}
    parsed_params = {k: v for k, v in parsed.items() if k != "text"}
    filters_dump = (
        body.filters.model_dump(mode="json", exclude_none=True) if body.filters else None
    )

    if body.snapshot_id:
        snap = get_snapshot(uid, body.snapshot_id)
        if snap is None:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Снимок выдачи устарел или не найден. Выполните поиск заново.",
            )
        full_rows = snap.items
        found = len(full_rows)
        per_page = body.per_page
        page = body.page
        start = page * per_page
        slice_dicts = full_rows[start : start + per_page]
        items_out = [CandidateOut(**d) for d in slice_dicts]
        pages = max(1, math.ceil(found / per_page)) if found else 1
        return SearchOut(
            items=items_out,
            found=found,
            page=page,
            pages=pages,
            per_page=per_page,
            parsed_params=snap.parsed_params,
            snapshot_id=body.snapshot_id.strip(),
            found_raw_hh=snap.found_raw_hh,
            found_telegram=snap.found_telegram,
            source_scope=snap.source_scope,
        )

    if body.page != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для страницы больше нуля укажите snapshot_id текущей выдачи "
            "или начните поиск с page=0.",
        )

    if body.source_scope in ("telegram", "all") and not settings.feature_use_telegram_source:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Поиск по Telegram отключён в конфигурации сервиса.",
        )

    scope = body.source_scope
    hh_rows: list[dict[str, Any]] = []
    hh_found = 0
    loaded_count = 0

    if scope in ("hh", "all"):
        access: str | None = None
        if not settings.feature_use_mock_hh:
            access = await ensure_hh_access_token(db, user.id)
            if not access:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Подключите HeadHunter для поиска по базе резюме",
                )
        else:
            access = None

        hh_page = max(1, min(settings.search_hh_page_size, 100))
        max_fetch = max(1, settings.search_max_resumes_fetch_per_search)

        try:
            raw_items, hh_found, loaded_count = await _fetch_hh_resume_pages(
                access,
                parsed,
                body.filters,
                max_resumes=max_fetch,
                per_page=hh_page,
                db=db,
                hh_token_user_id=user.id,
            )
        except PermissionError as e:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
        except HHClientError as e:
            raise HTTPException(status_code=e.status_code, detail=e.detail) from e
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="HeadHunter API недоступен",
            ) from exc

        hh_rows = _build_search_items(parsed, raw_items)

    tg_count = 0
    tg_serialized: list[dict[str, Any]] = []
    if scope in ("telegram", "all"):
        tg_raw = telegram_search.search_telegram_profiles(
            db,
            user.id,
            body.query,
            parsed,
            limit=max(1, settings.search_max_resumes_fetch_per_search),
        )
        tg_count = len(tg_raw)
        tg_serialized = _build_search_items(parsed, tg_raw)

    if scope == "hh":
        serialized = hh_rows
    elif scope == "telegram":
        serialized = tg_serialized
        hh_found = 0
        loaded_count = 0
    else:
        serialized = _merge_hh_telegram(hh_rows, tg_serialized)

    found = len(serialized)

    snap_payload = SearchSnapshotData(
        items=serialized,
        found_raw_hh=hh_found if scope != "telegram" else None,
        loaded_from_hh=loaded_count if scope != "telegram" else 0,
        parsed_params=parsed_params,
        query=body.query,
        filters=filters_dump,
        evaluated=False,
        analyzed=False,
        source_scope=scope,
        found_telegram=tg_count if scope in ("telegram", "all") else None,
    )
    snapshot_id = save_snapshot(uid, snap_payload)

    per_page = body.per_page
    start = 0
    slice_dicts = serialized[start : start + per_page]
    items_out = [CandidateOut(**d) for d in slice_dicts]
    pages = max(1, math.ceil(found / per_page)) if found else 1

    db.add(
        SearchHistory(
            user_id=user.id,
            query=body.query,
            filters=filters_dump,
            parsed_params=parsed_params,
            page=0,
            per_page=per_page,
            found=found,
        )
    )
    db.commit()

    return SearchOut(
        items=items_out,
        found=found,
        page=0,
        pages=pages,
        per_page=per_page,
        parsed_params=parsed_params,
        snapshot_id=snapshot_id,
        found_raw_hh=hh_found if scope != "telegram" else None,
        found_telegram=tg_count if scope in ("telegram", "all") else None,
        source_scope=scope,
    )
