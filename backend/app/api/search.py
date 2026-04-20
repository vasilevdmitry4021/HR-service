from __future__ import annotations

import asyncio
import json
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
from app.db.session import SessionLocal
from app.models.search_history import SearchHistory
from app.models.user import User
from app.schemas.search import (
    AnalyzeIn,
    AnalyzeOut,
    AnalyzeProgressOut,
    AnalyzeStartOut,
    CandidateOut,
    EvaluateCandidateOut,
    EvaluateIn,
    EvaluateOut,
    EvaluateProgressOut,
    EvaluateStartOut,
    SearchIn,
    SearchOut,
    SearchParseIn,
    SearchParseOut,
)
from app.services import hh_client
from app.services import hh_filter_mapper
from app.services import llm_client
from app.services import llm_evaluation
from app.services import skill_expansion
from app.services import analyze_progress
from app.services import evaluate_progress
from app.services import hh_query_planner
from app.services import nlp_service
from app.services import post_filter
from app.services.hh_client import HHClientError
from app.services.hh_errors import is_daily_view_limit_error
from app.services.search_snapshot_cache import (
    SearchSnapshotData,
    get_snapshot,
    replace_snapshot,
    save_snapshot,
)

router = APIRouter(prefix="/search", tags=["search"])

logger = logging.getLogger(__name__)
metrics_logger = logging.getLogger("search.metrics")


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
    if st != "hh":
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
        "match_source": str(r.get("match_source") or ""),
    }


def _strict_filters_payload(
    parsed: dict[str, Any],
    filters: Any,
) -> dict[str, Any]:
    payload = dict(parsed)
    fdict: dict[str, Any] = {}
    if hasattr(filters, "model_dump"):
        fdict = filters.model_dump(exclude_none=True)
    elif isinstance(filters, dict):
        fdict = {k: v for k, v in filters.items() if v is not None}
    payload_overrides = {
        "age_min": fdict.get("age_from"),
        "age_max": fdict.get("age_to"),
        "salary_from": fdict.get("salary_from"),
        "salary_to": fdict.get("salary_to"),
        "currency": fdict.get("currency"),
        "gender": fdict.get("gender"),
    }
    for k, v in payload_overrides.items():
        if v is not None:
            payload[k] = v
    return payload


def _build_search_items(
    parsed: dict[str, Any],
    raw_items: list[dict],
    filters: Any = None,
) -> list[dict[str, Any]]:
    filtered_items = raw_items
    if settings.strict_numeric_filters:
        strict_payload = _strict_filters_payload(parsed, filters)
        filtered_items = post_filter.apply_strict_filters(
            list(raw_items),
            strict_payload,
            mode=settings.strict_filter_mode,
        )
    filtered_items = list(filtered_items)
    filtered_items.sort(key=lambda r: (0 if r.get("strict_match", True) else 1))
    return [_candidate_dict_from_raw(r) for r in filtered_items]


def _snapshot_needs_hh_access(items: list[dict[str, Any]]) -> bool:
    return bool(items)


def _scores_map(rows: list[dict[str, Any]]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    for row in rows:
        rid = str(row.get("id", row.get("hh_resume_id", ""))).strip()
        if not rid:
            continue
        val = row.get("llm_score")
        if isinstance(val, int):
            out[rid] = int(val)
    return out


def _extract_model_score(row: dict[str, Any]) -> int | None:
    analysis = row.get("llm_analysis")
    if isinstance(analysis, dict):
        val = analysis.get("llm_score")
        if isinstance(val, int):
            return val
    val = row.get("llm_score")
    if isinstance(val, int):
        return val
    return None


def _extract_prescore(row: dict[str, Any]) -> int | None:
    val = row.get("llm_score")
    return val if isinstance(val, int) else None


def _extract_experience(row: dict[str, Any]) -> int | None:
    val = row.get("experience_years")
    return val if isinstance(val, int) else None


def _sort_snapshot_rows(rows: list[dict[str, Any]], sort_by: str) -> list[dict[str, Any]]:
    if sort_by == "server":
        return list(rows)

    indexed = list(enumerate(rows))

    def _desc_key(score: int | None, index: int) -> tuple[int, int, int]:
        if score is None:
            return (1, 0, index)
        return (0, -score, index)

    def _asc_key(score: int | None, index: int) -> tuple[int, int, int]:
        if score is None:
            return (1, 0, index)
        return (0, score, index)

    if sort_by == "llm_desc":
        indexed.sort(
            key=lambda it: _desc_key(_extract_model_score(it[1]), it[0])
        )
    elif sort_by == "llm_score_desc":
        indexed.sort(
            key=lambda it: _desc_key(_extract_prescore(it[1]), it[0])
        )
    elif sort_by == "experience_desc":
        indexed.sort(
            key=lambda it: _desc_key(_extract_experience(it[1]), it[0])
        )
    elif sort_by == "experience_asc":
        indexed.sort(
            key=lambda it: _asc_key(_extract_experience(it[1]), it[0])
        )
    else:
        return list(rows)
    return [row for _, row in indexed]


async def _run_evaluate_job(
    *,
    job_id: str,
    user_id: str,
    user_uuid: uuid.UUID,
    snapshot_id: str,
    access: str | None,
) -> None:
    evaluate_progress.mark_running(job_id)
    started = time.monotonic()
    db = SessionLocal()
    try:
        snap = get_snapshot(user_id, snapshot_id)
        if snap is None:
            evaluate_progress.mark_failed(job_id, "Снимок выдачи устарел или не найден.")
            return

        parsed = {**snap.parsed_params, "text": snap.query}
        base_rows: list[dict[str, Any]] = []
        for d in snap.items:
            nd = dict(d)
            nd["llm_score"] = None
            nd["llm_analysis"] = None
            base_rows.append(nd)

        def on_progress(evt: dict[str, Any]) -> None:
            stage = str(evt.get("stage") or "running")
            phase = str(evt.get("phase") or "").strip() or None
            stage_ui = stage
            if stage == "enrichment":
                stage_ui = "preparing"
            elif stage == "prescore":
                stage_ui = "evaluating_top" if phase == "interactive" else "evaluating_rest"
            elif stage == "phase_done":
                phase_total = int(evt.get("phase_total_count") or 0)
                has_background = len(base_rows) > phase_total
                if phase == "interactive" and has_background:
                    stage_ui = "evaluating_rest"
                elif phase == "background" or (phase == "interactive" and not has_background):
                    stage_ui = "done"
            evaluate_progress.update_stage(job_id, stage_ui)
            if phase:
                evaluate_progress.update_phase(job_id, phase)
            if stage == "prescore":
                # Публикуем частичные оценки батчами для polling на фронте.
                total_count = int(evt.get("total_count") or len(base_rows))
                counters: dict[str, int] = {"total_count": len(base_rows)}
                if phase == "interactive":
                    counters["interactive_total_count"] = total_count
                elif phase == "background":
                    counters["background_total_count"] = total_count
                evaluate_progress.update_counters(job_id, **counters)
                metrics_patch: dict[str, Any] = {}
                if evt.get("llm_calls_refill") is not None:
                    metrics_patch["llm_calls_refill"] = int(evt.get("llm_calls_refill") or 0)
                if evt.get("llm_scored_count") is not None:
                    metrics_patch["llm_scored_count"] = int(evt.get("llm_scored_count") or 0)
                if evt.get("fallback_scored_count") is not None:
                    metrics_patch["fallback_scored_count"] = int(
                        evt.get("fallback_scored_count") or 0
                    )
                if evt.get("scored_count") is not None:
                    if phase:
                        metrics_patch[f"{phase}_scored_count"] = int(
                            evt.get("scored_count") or 0
                        )
                    else:
                        metrics_patch["scored_count"] = int(evt.get("scored_count") or 0)
                evaluate_progress.merge_metrics(job_id, metrics_patch)
                delta = evt.get("scores_delta")
                if isinstance(delta, dict):
                    score_source = "fallback" if str(evt.get("event") or "") == "fallback_done" else "llm"
                    patch: dict[str, int | None] = {}
                    for rid, score in delta.items():
                        key = str(rid).strip()
                        if not key:
                            continue
                        patch[key] = score if isinstance(score, int) else None
                    if patch:
                        evaluate_progress.add_partial_scores(
                            job_id,
                            patch,
                            phase=phase,
                            score_source=score_source,
                        )
            elif stage == "phase_done":
                phase_total = int(evt.get("phase_total_count") or 0)
                phase_scored = int(evt.get("phase_scored_count") or 0)
                phase_llm_scored = int(evt.get("phase_llm_scored_count") or 0)
                phase_fallback = int(evt.get("phase_fallback_count") or 0)
                phase_unresolved = int(evt.get("phase_unresolved_count") or 0)
                if phase == "interactive":
                    evaluate_progress.update_counters(
                        job_id,
                        interactive_total_count=phase_total,
                    )
                    evaluate_progress.merge_metrics(
                        job_id,
                        {
                            "interactive_scored_count": phase_scored,
                            "interactive_llm_scored_count": phase_llm_scored,
                            "interactive_fallback_count": phase_fallback,
                            "interactive_unresolved_count": phase_unresolved,
                        },
                    )
                elif phase == "background":
                    evaluate_progress.update_counters(
                        job_id,
                        background_total_count=phase_total,
                    )
                    evaluate_progress.merge_metrics(
                        job_id,
                        {
                            "background_scored_count": phase_scored,
                            "background_llm_scored_count": phase_llm_scored,
                            "background_fallback_count": phase_fallback,
                            "background_unresolved_count": phase_unresolved,
                        },
                    )

        eval_result = await llm_evaluation.evaluate_all_resumes(
            access,
            base_rows,
            parsed,
            db,
            user_id=user_uuid,
            progress_callback=on_progress,
        )
        if isinstance(eval_result, tuple):
            updated, metrics = eval_result
        else:
            updated, metrics = eval_result, {}

        new_snap = SearchSnapshotData(
            items=updated,
            found_raw_hh=snap.found_raw_hh,
            loaded_from_hh=snap.loaded_from_hh,
            parsed_params=snap.parsed_params,
            query=snap.query,
            filters=snap.filters,
            search_metrics=snap.search_metrics,
            evaluated=True,
            analyzed=False,
            source_scope=snap.source_scope,
        )
        replace_snapshot(user_id, snapshot_id, new_snap)
        scores_map = _scores_map(updated)
        terminal_status = str(metrics.get("status") or "done")
        llm_only_complete = bool(metrics.get("llm_only_complete"))
        if terminal_status == "done" and llm_only_complete:
            evaluate_progress.mark_done(
                job_id,
                scores=scores_map,
                processing_time_seconds=time.monotonic() - started,
                metrics=metrics,
            )
        elif terminal_status == "error":
            evaluate_progress.merge_metrics(job_id, metrics)
            unresolved_count = int(metrics.get("unresolved_count") or 0)
            evaluate_progress.mark_failed(
                job_id,
                (
                    f"Оценка завершилась ошибкой: без LLM-score осталось {unresolved_count} резюме."
                    if unresolved_count > 0
                    else "Оценка завершилась ошибкой: не получены LLM-score."
                ),
            )
        else:
            unresolved_count = int(metrics.get("unresolved_count") or 0)
            evaluate_progress.mark_partial(
                job_id,
                scores=scores_map,
                processing_time_seconds=time.monotonic() - started,
                metrics=metrics,
                error=(
                    f"Оценка завершена частично: без LLM-score осталось {unresolved_count} резюме."
                    if unresolved_count > 0
                    else "Оценка завершена частично: не все резюме получили LLM-score."
                ),
            )
    except HHClientError as exc:
        logger.warning("Оценка снимка остановлена ошибкой HH: %s", exc.detail)
        evaluate_progress.mark_failed(job_id, exc.detail)
    except Exception as exc:
        logger.exception("Ошибка оценки снимка в фоне: %s", exc)
        evaluate_progress.mark_failed(job_id, "Не удалось выполнить оценку резюме")
    finally:
        db.close()


async def _run_analyze_job(
    *,
    job_id: str,
    user_id: str,
    snapshot_id: str,
    access: str | None,
    top_n: int,
) -> None:
    analyze_progress.mark_running(job_id)
    started = time.monotonic()
    db = SessionLocal()
    try:
        snap = get_snapshot(user_id, snapshot_id)
        if snap is None:
            analyze_progress.mark_failed(job_id, "Снимок выдачи устарел или не найден.")
            return
        if not any(isinstance(x.get("llm_score"), int) for x in snap.items):
            analyze_progress.mark_failed(
                job_id, "Сначала выполните оценку выдачи (evaluate)."
            )
            return

        parsed = {**snap.parsed_params, "text": snap.query}

        def _progress(evt: dict[str, Any]) -> None:
            stage = str(evt.get("stage") or "running")
            if stage == "start":
                stage = "preparing"
            processed = int(evt.get("processed_count") or 0)
            analyzed = int(evt.get("analyzed_count") or 0)
            analyze_progress.update_progress(
                job_id,
                stage=stage,
                processed_count=processed,
                analyzed_count=analyzed,
            )
            delta = evt.get("analyses_delta")
            if isinstance(delta, dict) and delta:
                analyze_progress.add_partial_analyses(job_id, delta)

        updated = await llm_evaluation.analyze_top_resumes(
            access,
            list(snap.items),
            parsed,
            user_id=user_id,
            query=snap.query,
            top_n=top_n,
            db=db,
            progress_callback=_progress,
        )
        processed_count = min(len(updated), max(1, int(top_n)))
        analyzed_n = sum(1 for x in updated if x.get("llm_analysis"))
        new_snap = SearchSnapshotData(
            items=updated,
            found_raw_hh=snap.found_raw_hh,
            loaded_from_hh=snap.loaded_from_hh,
            parsed_params=snap.parsed_params,
            query=snap.query,
            filters=snap.filters,
            search_metrics=snap.search_metrics,
            evaluated=True,
            analyzed=True,
            source_scope=snap.source_scope,
        )
        replace_snapshot(user_id, snapshot_id, new_snap)
        analyze_progress.mark_done(
            job_id,
            processed_count=processed_count,
            analyzed_count=analyzed_n,
            processing_time_seconds=time.monotonic() - started,
        )
    except HHClientError as exc:
        detail = exc.detail
        if is_daily_view_limit_error(exc.detail):
            detail = (
                f"{exc.detail}. Ошибка связана с превышением дневного лимита "
                "на просмотр резюме в HeadHunter."
            )
        analyze_progress.mark_failed(job_id, detail)
    except Exception as exc:
        logger.exception("Ошибка детального анализа в фоне: %s", exc)
        analyze_progress.mark_failed(job_id, "Не удалось выполнить детальный анализ")
    finally:
        db.close()


async def _fetch_hh_resume_pages(
    access: str | None,
    parsed: dict[str, Any],
    filters: Any,
    *,
    plans: list[hh_query_planner.HHQueryPlan] | None = None,
    effective_area_ids: list[int] | None = None,
    professional_role_ids: list[int] | None = None,
    max_resumes: int,
    per_page: int,
    db: Session | None = None,
    hh_token_user_id: uuid.UUID | None = None,
) -> tuple[list[dict[str, Any]], int, int, dict[str, Any]]:
    """Собирает резюме с HH по одному или нескольким query-планам."""
    all_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    page_size = max(1, min(int(per_page), 100))
    cap = max(0, int(max_resumes))
    found_total = 0
    query_metrics: list[dict[str, Any]] = []
    relax_used = False
    relax_steps_used = 0
    primary_found = 0
    primary_loaded = 0

    if not plans:
        plans = [
            hh_query_planner.HHQueryPlan(
                label="legacy",
                text="",
                priority=1,
            )
        ]

    async def _fetch_by_plan(
        plan: hh_query_planner.HHQueryPlan,
        *,
        relax_step: int = 0,
    ) -> tuple[int, int]:
        nonlocal relax_used, relax_steps_used
        local_found = 0
        local_loaded = 0
        local_raw = 0
        page = 0
        while len(all_items) < cap:
            chunk, found = await hh_client.search_resumes(
                access,
                parsed,
                filters,
                page,
                page_size,
                query_plan=plan if plan.text else None,
                professional_role_ids=professional_role_ids,
                db=db,
                hh_token_user_id=hh_token_user_id,
            )
            local_found = int(found)
            if not chunk:
                break
            local_raw += len(chunk)
            room = cap - len(all_items)
            if room <= 0:
                break
            added_on_page = 0
            for item in chunk:
                rid = str(item.get("id") or "").strip()
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)
                item["match_source"] = plan.label.split("_split_")[0]
                all_items.append(item)
                added_on_page += 1
                local_loaded += 1
                if len(all_items) >= cap:
                    break
            if len(chunk) < page_size or added_on_page == 0:
                break
            page += 1
        query_metrics.append(
            {
                "label": plan.label,
                "text": (plan.text or "")[:240],
                "found": local_found,
                "returned": local_loaded,
                "raw": local_raw,
                "relax_step": relax_step,
                "relaxed": relax_step > 0,
                "group_kinds": [kind for kind, _ in plan.groups],
                "must_groups": sum(1 for kind, _ in plan.groups if kind.startswith("must_")),
                "risky_groups": sum(1 for kind, _ in plan.groups if "risky" in kind),
                "group_term_sizes": {
                    kind: max(1, len([t for t in text.strip("()").split(" OR ") if t.strip()]))
                    for kind, text in plan.groups
                },
            }
        )
        if relax_step > 0:
            relax_used = True
            relax_steps_used = max(relax_steps_used, int(relax_step))
        return local_found, local_loaded

    primary_candidates = [p for p in plans if p.label.startswith("primary")]
    if not primary_candidates:
        primary_candidates = [plans[0]]
    primary_base = primary_candidates[0]
    found, loaded = await _fetch_by_plan(primary_base, relax_step=0)
    found_total = max(found_total, found)
    primary_found = int(found)
    primary_loaded = int(loaded)

    base_target_min = max(0, int(settings.search_recall_target_min))
    target_min = base_target_min
    if effective_area_ids:
        target_min = max(
            0,
            min(
                base_target_min,
                int(settings.search_recall_target_min_with_area or base_target_min),
            ),
        )
    relax_max_steps = max(0, int(settings.hh_query_relax_max_steps or 3))
    if effective_area_ids:
        relax_max_steps = max(
            0,
            min(
                relax_max_steps,
                int(settings.hh_query_relax_max_steps_with_area or relax_max_steps),
            ),
        )
    if found < target_min:
        for step in range(1, relax_max_steps + 1):
            relaxed = hh_query_planner.relax(primary_base, step)
            if not relaxed.text:
                break
            found_relaxed, _ = await _fetch_by_plan(relaxed, relax_step=step)
            found_total = max(found_total, found_relaxed)
            if found_relaxed >= target_min:
                break

    needs_recall = target_min > 0 and len(all_items) < target_min
    for extra_plan in plans:
        if extra_plan.label.startswith("primary"):
            continue
        if extra_plan.label.startswith("broad") and not needs_recall:
            continue
        if len(all_items) >= cap:
            break
        await _fetch_by_plan(extra_plan, relax_step=0)
        needs_recall = target_min > 0 and len(all_items) < target_min

    metrics = {
        "queries": query_metrics,
        "recall_pool_size": len(all_items),
        "raw_pool_size": len(all_items),
        "dedup_dropped": max(0, sum(m["raw"] for m in query_metrics) - len(all_items)),
        "relax_used": relax_used,
        "relax_steps_used": relax_steps_used,
        "primary_found": primary_found,
        "primary_loaded": primary_loaded,
        "recall_target_min_base": base_target_min,
        "recall_target_min_used": target_min,
        "area_applied": bool(effective_area_ids),
    }
    return all_items, found_total, len(all_items), metrics


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
        eval_result = await llm_evaluation.evaluate_all_resumes(
            access,
            base_rows,
            parsed,
            db,
            user_id=user.id,
        )
        if isinstance(eval_result, tuple):
            updated, metrics = eval_result
        else:
            updated, metrics = eval_result, {}
    except HHClientError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
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
        search_metrics=snap.search_metrics,
        evaluated=True,
        analyzed=False,
        source_scope=snap.source_scope,
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
        llm_scored_count=int(metrics.get("llm_scored_count") or scored),
        fallback_scored_count=int(metrics.get("fallback_scored_count") or 0),
        coverage_ratio=round(float(metrics.get("coverage_ratio") or ((scored / len(updated)) if updated else 1.0)), 4),
        processing_time_seconds=round(elapsed, 3),
        metrics=metrics,
    )


@router.post("/{snapshot_id}/analyze", response_model=AnalyzeOut)
async def analyze_resumes(
    snapshot_id: str,
    body: AnalyzeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalyzeOut:
    # Совместимый синхронный endpoint (deprecated): новый контракт — analyze/start + analyze/progress.
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
    except HHClientError as exc:
        detail = exc.detail
        if is_daily_view_limit_error(exc.detail):
            detail = (
                f"{exc.detail}. Ошибка связана с превышением дневного лимита "
                "на просмотр резюме в HeadHunter."
            )
        raise HTTPException(
            status_code=exc.status_code,
            detail=detail,
        ) from exc
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
        search_metrics=snap.search_metrics,
        evaluated=True,
        analyzed=True,
        source_scope=snap.source_scope,
    )
    replace_snapshot(uid, snapshot_id, new_snap)

    items_out = [CandidateOut(**x) for x in updated]
    return AnalyzeOut(
        items=items_out,
        analyzed_count=analyzed_n,
        processing_time_seconds=round(elapsed, 3),
    )


@router.post("/{snapshot_id}/evaluate/start", response_model=EvaluateStartOut)
async def evaluate_resumes_start(
    snapshot_id: str,
    body: EvaluateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EvaluateStartOut:
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

    job_id = evaluate_progress.create_job(
        user_id=uid,
        snapshot_id=snapshot_id,
        total_count=len(snap.items),
    )
    interactive_total = min(
        len(snap.items),
        max(1, int(settings.evaluate_interactive_top_n or 50)),
    )
    evaluate_progress.update_counters(
        job_id,
        total_count=len(snap.items),
        interactive_total_count=interactive_total,
        background_total_count=max(0, len(snap.items) - interactive_total),
    )
    asyncio.create_task(
        _run_evaluate_job(
            job_id=job_id,
            user_id=uid,
            user_uuid=user.id,
            snapshot_id=snapshot_id,
            access=access,
        )
    )
    return EvaluateStartOut(job_id=job_id, status="queued", total_count=len(snap.items))


@router.post("/{snapshot_id}/analyze/start", response_model=AnalyzeStartOut)
async def analyze_resumes_start(
    snapshot_id: str,
    body: AnalyzeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AnalyzeStartOut:
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

    top_n = max(1, min(50, int(body.top_n)))
    total_count = min(len(snap.items), top_n)
    job_id = analyze_progress.create_job(
        user_id=uid,
        snapshot_id=snapshot_id,
        total_count=total_count,
    )
    analyze_progress.update_progress(
        job_id,
        stage="queued",
        processed_count=0,
        analyzed_count=0,
    )
    asyncio.create_task(
        _run_analyze_job(
            job_id=job_id,
            user_id=uid,
            snapshot_id=snapshot_id,
            access=access,
            top_n=top_n,
        )
    )
    return AnalyzeStartOut(job_id=job_id, status="queued", total_count=total_count)


@router.get("/{snapshot_id}/analyze/progress", response_model=AnalyzeProgressOut)
async def analyze_resumes_progress(
    snapshot_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
) -> AnalyzeProgressOut:
    state = analyze_progress.get_job(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача анализа не найдена или истекла.",
        )
    if str(state.get("user_id")) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к задаче анализа.",
        )
    if str(state.get("snapshot_id")) != snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="job_id не относится к указанному snapshot_id.",
        )
    return AnalyzeProgressOut(
        job_id=str(state.get("job_id") or job_id),
        status=str(state.get("status") or "queued"),
        stage=str(state.get("stage") or "queued"),
        total_count=int(state.get("total_count") or 0),
        processed_count=int(state.get("processed_count") or 0),
        analyzed_count=int(state.get("analyzed_count") or 0),
        analyses=dict(state.get("analyses") or {}),
        processing_time_seconds=state.get("processing_time_seconds"),
        error=state.get("error"),
    )


@router.get("/{snapshot_id}/evaluate/progress", response_model=EvaluateProgressOut)
async def evaluate_resumes_progress(
    snapshot_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
) -> EvaluateProgressOut:
    state = evaluate_progress.get_job(job_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задача оценки не найдена или истекла.",
        )

    if str(state.get("user_id")) != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нет доступа к задаче оценки.",
        )
    if str(state.get("snapshot_id")) != snapshot_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="job_id не относится к указанному snapshot_id.",
        )

    scores = state.get("scores") or {}
    items = [
        EvaluateCandidateOut(id=str(rid), llm_score=score if isinstance(score, int) else None)
        for rid, score in sorted(scores.items(), key=lambda item: str(item[0]))
    ]
    return EvaluateProgressOut(
        job_id=str(state.get("job_id") or job_id),
        status=str(state.get("status") or "queued"),
        stage=str(state.get("stage") or "queued"),
        phase=str(state.get("phase") or "interactive"),
        total_count=int(state.get("total_count") or 0),
        scored_count=int(state.get("scored_count") or 0),
        llm_scored_count=int(state.get("llm_scored_count") or 0),
        fallback_scored_count=int(state.get("fallback_scored_count") or 0),
        coverage_ratio=float(state.get("coverage_ratio") or 0.0),
        llm_coverage_ratio=float(state.get("llm_coverage_ratio") or state.get("coverage_ratio") or 0.0),
        unresolved_count=int(state.get("unresolved_count") or 0),
        llm_only_complete=bool(state.get("llm_only_complete")),
        completed_count=int(state.get("completed_count") or 0),
        interactive_total_count=int(state.get("interactive_total_count") or 0),
        background_total_count=int(state.get("background_total_count") or 0),
        interactive_done_count=int(state.get("interactive_done_count") or 0),
        background_done_count=int(state.get("background_done_count") or 0),
        interactive_llm_scored_count=int(state.get("interactive_llm_scored_count") or 0),
        background_llm_scored_count=int(state.get("background_llm_scored_count") or 0),
        interactive_fallback_count=int(state.get("interactive_fallback_count") or 0),
        background_fallback_count=int(state.get("background_fallback_count") or 0),
        items=items,
        processing_time_seconds=state.get("processing_time_seconds"),
        error=state.get("error"),
        metrics=dict(state.get("metrics") or {}),
    )


@router.post("", response_model=SearchOut)
async def search(
    body: SearchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SearchOut:
    search_started = time.monotonic()
    uid = str(user.id)
    search_mode = body.search_mode if body.search_mode in {"precise", "mass"} else "precise"
    parsed, _conf, _ms = nlp_service.parse_natural_query(body.query, db=db)
    parsed = {**parsed, "text": body.query, "search_mode": search_mode}
    parsed_params = {k: v for k, v in parsed.items() if k != "text"}
    parsed_params.setdefault("expanded_synonyms", {})
    parsed_params["search_mode"] = search_mode
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
        sorted_rows = _sort_snapshot_rows(full_rows, body.sort_by)
        found = len(sorted_rows)
        per_page = body.per_page
        page = body.page
        start = page * per_page
        slice_dicts = sorted_rows[start : start + per_page]
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
            search_metrics=snap.search_metrics,
            source_scope=snap.source_scope,
            search_mode=(
                str(snap.parsed_params.get("search_mode"))
                if isinstance(snap.parsed_params.get("search_mode"), str)
                else "precise"
            ),
        )

    if body.page != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Для страницы больше нуля укажите snapshot_id текущей выдачи "
            "или начните поиск с page=0.",
        )

    scope = body.source_scope
    hh_rows: list[dict[str, Any]] = []
    hh_found = 0
    loaded_count = 0
    search_metrics: dict[str, Any] = {
        "query_id": str(uuid.uuid4()),
        "feature_hh_boolean_query": bool(settings.feature_hh_boolean_query),
        "latency_ms": {},
        "hh_queries": [],
        "llm_cost": {"parse_tokens": None, "expand_tokens": None, "prescore_tokens": None, "usd": None},
        "skill_expansion_cache": {},
        "relax_used": False,
        "risky_terms_total": 0,
        "risky_terms_demoted_to_should": 0,
        "risky_terms_demoted_to_soft": 0,
        "semantic_jargon_terms_total": 0,
        "semantic_terms_promoted_to_should": 0,
        "semantic_terms_promoted_to_must": 0,
        "semantic_terms_demoted_to_soft": 0,
        "semantic_profile": [],
        "hard_terms_used_in_primary": 0,
        "area": {
            "effective": None,
            "effective_ids": [],
            "source": "none",
            "parsed_region": parsed.get("region"),
        },
        "primary_found": 0,
        "relax_steps_used": 0,
        "raw_pool_size": 0,
        "count_after_strict_filter": 0,
        "search_mode": search_mode,
        "role_strategy": "professional_role_only",
        "skills_strategy": f"skills_in_text_{'and' if search_mode == 'precise' else 'or'}",
        "text_operator": "AND" if search_mode == "precise" else "OR",
        "professional_role_resolution_source": "none",
        "professional_role_match_debug": [],
        "professional_role_ids": [],
        "skill_ids": [],
        "text_terms": [],
    }

    if scope == "hh":
        effective_area_ids, area_source = hh_filter_mapper.resolve_area_priority(parsed, body.filters)
        search_metrics["area"] = {
            "effective": effective_area_ids[0] if effective_area_ids else None,
            "effective_ids": effective_area_ids or [],
            "source": area_source,
            "parsed_region": parsed.get("region"),
        }
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

        resolved_professional_role_ids: list[int] = []
        resolved_professional_role_debug: list[dict[str, Any]] = []
        professional_role_reference = None
        explicit_professional_role = (
            body.filters.professional_role
            if body.filters is not None and body.filters.professional_role is not None
            else None
        )
        if explicit_professional_role is not None:
            search_metrics["professional_role_resolution_source"] = "panel"
        elif settings.feature_hh_auto_professional_role:
            try:
                professional_role_reference, role_source = await hh_client.get_professional_roles_reference(
                    access,
                    db=db,
                    hh_token_user_id=user.id,
                )
                search_metrics["professional_role_resolution_source"] = role_source
            except HHClientError as exc:
                logger.warning(
                    "Не удалось загрузить справочник professional_roles: %s",
                    exc.detail,
                )
                search_metrics["professional_role_resolution_source"] = "none"
            except Exception as exc:
                logger.warning(
                    "Ошибка загрузки справочника professional_roles: %s",
                    exc,
                )
                search_metrics["professional_role_resolution_source"] = "none"
            if professional_role_reference is not None:
                (
                    resolved_professional_role_ids,
                    resolved_professional_role_debug,
                ) = hh_filter_mapper.resolve_professional_roles(
                    parsed,
                    professional_role_reference,
                )
                search_metrics["professional_role_match_debug"] = resolved_professional_role_debug
                search_metrics["professional_role_ids"] = resolved_professional_role_ids

        hh_page = max(1, min(settings.search_hh_page_size, 100))
        max_fetch = max(
            1,
            settings.search_max_recall
            if settings.feature_hh_boolean_query
            else settings.search_max_resumes_fetch_per_search,
        )

        plans: list[hh_query_planner.HHQueryPlan] | None = None
        if settings.feature_hh_boolean_query:
            t_expand = time.monotonic()
            canonical_skills: list[str] = []
            for group_key in ("must_skills", "should_skills"):
                raw_groups = parsed.get(group_key)
                if not isinstance(raw_groups, list):
                    continue
                for item in raw_groups:
                    if isinstance(item, dict):
                        canonical = str(item.get("canonical") or "").strip()
                        if canonical:
                            canonical_skills.append(canonical)
            expanded, expand_stats = skill_expansion.expand_skills_with_stats(canonical_skills, db)
            parsed_classification = skill_expansion.classify_parsed_skills(
                parsed,
                expanded,
                expansion_stats=expand_stats,
            )
            parsed.update(parsed_classification)
            parsed["expanded_synonyms"] = expanded
            parsed_params.update(parsed_classification)
            parsed_params["expanded_synonyms"] = expanded
            search_metrics["latency_ms"]["expand"] = int((time.monotonic() - t_expand) * 1000)
            search_metrics["skill_expansion_cache"] = expand_stats

            t_plan = time.monotonic()
            plans = hh_query_planner.build_plans(parsed, expanded, search_mode=search_mode)
            search_metrics["latency_ms"]["plan"] = int((time.monotonic() - t_plan) * 1000)
            search_metrics["risky_terms_total"] = len(parsed.get("risky_skills") or [])
            search_metrics["risky_terms_demoted_to_should"] = int(
                parsed.get("risky_demoted_to_should") or 0
            )
            search_metrics["risky_terms_demoted_to_soft"] = int(
                parsed.get("risky_demoted_to_soft") or 0
            )
            search_metrics["semantic_jargon_terms_total"] = int(
                parsed.get("semantic_jargon_terms_total") or 0
            )
            search_metrics["semantic_terms_promoted_to_should"] = int(
                parsed.get("semantic_terms_promoted_to_should") or 0
            )
            search_metrics["semantic_terms_promoted_to_must"] = int(
                parsed.get("semantic_terms_promoted_to_must") or 0
            )
            search_metrics["semantic_terms_demoted_to_soft"] = int(
                parsed.get("semantic_terms_demoted_to_soft") or 0
            )
            raw_profile = parsed.get("semantic_profile")
            if isinstance(raw_profile, list):
                search_metrics["semantic_profile"] = [
                    {
                        "canonical": str(x.get("canonical") or "").strip(),
                        "intent_strength": str(x.get("intent_strength") or "").strip(),
                        "query_confidence": x.get("query_confidence"),
                        "target_bucket": str(x.get("target_bucket") or x.get("bucket") or "").strip(),
                    }
                    for x in raw_profile
                    if isinstance(x, dict) and str(x.get("canonical") or "").strip()
                ]
            primary_plan = next((p for p in plans if p.label == "primary"), None) if plans else None
            search_metrics["hard_terms_used_in_primary"] = int(
                sum(1 for kind, _ in (primary_plan.groups if primary_plan else ()) if kind == "skills")
            )
            if primary_plan is not None:
                search_metrics["text_terms"] = [
                    text.strip() for kind, text in primary_plan.groups if kind == "skills" and text.strip()
                ]

            params_for_diagnostics = hh_filter_mapper.merge_resume_search_params(
                parsed,
                body.filters,
                page=0,
                per_page=body.per_page,
                query_plan=primary_plan,
                search_mode=search_mode,
                professional_role_ids=resolved_professional_role_ids,
                professional_roles_reference=professional_role_reference,
            )
            if not search_metrics["professional_role_ids"]:
                raw_roles = params_for_diagnostics.get("professional_role")
                if isinstance(raw_roles, list):
                    search_metrics["professional_role_ids"] = [
                        int(x) for x in raw_roles if isinstance(x, int)
                    ]
                elif isinstance(raw_roles, int):
                    search_metrics["professional_role_ids"] = [raw_roles]
            raw_skill_ids = params_for_diagnostics.get("skill")
            if isinstance(raw_skill_ids, list):
                search_metrics["skill_ids"] = [int(x) for x in raw_skill_ids if isinstance(x, int)]

        try:
            t_fetch = time.monotonic()
            raw_items, hh_found, loaded_count, hh_fetch_metrics = await _fetch_hh_resume_pages(
                access,
                parsed,
                body.filters,
                plans=plans,
                effective_area_ids=effective_area_ids,
                professional_role_ids=resolved_professional_role_ids,
                max_resumes=max_fetch,
                per_page=hh_page,
                db=db,
                hh_token_user_id=user.id,
            )
            search_metrics["latency_ms"]["fetch"] = int((time.monotonic() - t_fetch) * 1000)
            search_metrics["hh_queries"] = hh_fetch_metrics.get("queries", [])
            search_metrics["relax_used"] = bool(hh_fetch_metrics.get("relax_used"))
            search_metrics["relax_steps_used"] = int(hh_fetch_metrics.get("relax_steps_used") or 0)
            search_metrics["primary_found"] = int(hh_fetch_metrics.get("primary_found") or 0)
            search_metrics["recall_pool_size"] = int(hh_fetch_metrics.get("recall_pool_size") or 0)
            search_metrics["raw_pool_size"] = int(hh_fetch_metrics.get("raw_pool_size") or 0)
            search_metrics["dedup_dropped"] = int(hh_fetch_metrics.get("dedup_dropped") or 0)
            search_metrics["recall_target_min_base"] = int(
                hh_fetch_metrics.get("recall_target_min_base")
                or settings.search_recall_target_min
            )
            search_metrics["recall_target_min_used"] = int(
                hh_fetch_metrics.get("recall_target_min_used")
                or settings.search_recall_target_min
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

        hh_rows = _build_search_items(parsed, raw_items, body.filters)
        search_metrics["count_after_strict_filter"] = len(hh_rows)

    serialized = hh_rows

    sorted_serialized = _sort_snapshot_rows(serialized, body.sort_by)
    found = len(sorted_serialized)

    snap_payload = SearchSnapshotData(
        items=serialized,
        found_raw_hh=hh_found,
        loaded_from_hh=loaded_count,
        parsed_params=parsed_params,
        query=body.query,
        filters=filters_dump,
        search_metrics=search_metrics,
        evaluated=False,
        analyzed=False,
        source_scope=scope,
    )
    snapshot_id = save_snapshot(uid, snap_payload)

    per_page = body.per_page
    start = 0
    slice_dicts = sorted_serialized[start : start + per_page]
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

    try:
        search_metrics["latency_ms"]["parse"] = int(_ms or 0)
        search_metrics["latency_ms"]["total"] = int((time.monotonic() - search_started) * 1000)
        search_metrics["source_scope"] = scope
        search_metrics["result_count"] = found
        search_metrics["top_match_sources"] = {
            "primary": sum(1 for x in serialized if x.get("match_source") == "primary"),
            "broad": sum(1 for x in serialized if x.get("match_source") == "broad"),
            "bonus": sum(1 for x in serialized if x.get("match_source") == "bonus"),
        }
        metrics_logger.info(json.dumps(search_metrics, ensure_ascii=False))
    except Exception:
        logger.exception("Не удалось записать метрики поиска")

    return SearchOut(
        items=items_out,
        found=found,
        page=0,
        pages=pages,
        per_page=per_page,
        parsed_params=parsed_params,
        snapshot_id=snapshot_id,
        found_raw_hh=hh_found,
        search_metrics=search_metrics,
        source_scope=scope,
        search_mode=search_mode,
    )
