"""Синхронная оценка снимка поиска: pre-screening и детальный анализ топ-N."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.services import hh_client
from app.services import llm_client
from app.services import llm_analysis_cache
from app.services import llm_prescoring
from app.services import llm_resume_analyzer
from app.services import resume_cache
from app.services.hh_client import HHClientError
from app.services.hh_errors import is_daily_view_limit_error

logger = logging.getLogger(__name__)


def _resume_row_id(d: dict[str, Any]) -> str:
    return str(d.get("id", d.get("hh_resume_id", "")))


def _candidate_stub_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Минимальная карточка кандидата для pre-screening."""
    return {
        "id": row.get("id"),
        "hh_resume_id": row.get("hh_resume_id"),
        "hh_resume_url": row.get("hh_resume_url"),
        "title": row.get("title", ""),
        "full_name": row.get("full_name", ""),
        "age": row.get("age"),
        "experience_years": row.get("experience_years"),
        "salary": row.get("salary"),
        "skills": list(row.get("skills") or []),
        "area": row.get("area", ""),
        "match_source": row.get("match_source"),
    }


def _compact_work_experience_for_prescore(
    row: dict[str, Any],
    *,
    max_items: int = 3,
    max_description_chars: int = 260,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in (row.get("work_experience") or [])[: max(0, max_items)]:
        if not isinstance(item, dict):
            continue
        position = str(item.get("position") or "").strip()
        company = str(item.get("company") or "").strip()
        description = str(item.get("description") or "").strip()
        if description and len(description) > max_description_chars:
            description = description[: max_description_chars - 1] + "…"
        compact: dict[str, str] = {}
        if position:
            compact["position"] = position
        if company:
            compact["company"] = company
        if description:
            compact["description"] = description
        if compact:
            out.append(compact)
    return out


def _prescore_payload_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Компактный payload для prescore: fallback-friendly и пригодный для semantic summary."""
    payload = _candidate_stub_from_row(row)
    about = str(row.get("about") or "").strip()
    if about:
        payload["about"] = about[:600]
    work = _compact_work_experience_for_prescore(row)
    if work:
        payload["work_experience"] = work
    raw_text = str(row.get("raw_text") or "").strip()
    if raw_text:
        payload["raw_text"] = raw_text[:2200]
    provided_summary = str(row.get("semantic_summary") or "").strip()
    if provided_summary:
        payload["semantic_summary"] = provided_summary[:1700]
    elif about or work or raw_text:
        payload["semantic_summary"] = llm_resume_analyzer.build_prescore_semantic_summary(
            row,
            max_chars=1700,
            highlights_limit=8,
            recent_jobs_limit=3,
        )
    return payload


def _sort_by_simple_criteria(
    resumes: list[dict[str, Any]],
    parsed_params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Предварительная сортировка до подгрузки полных резюме: опыт, пересечение навыков, заголовок."""

    def exp_value(r: dict[str, Any]) -> float:
        raw = r.get("experience_years")
        try:
            return float(raw) if raw is not None else -1.0
        except (TypeError, ValueError):
            return -1.0

    def skill_overlap(r: dict[str, Any]) -> int:
        required = [
            str(s).lower().strip()
            for s in (parsed_params.get("skills") or [])
            if str(s).strip()
        ]
        if not required:
            return 0
        cand = [str(s).lower().strip() for s in (r.get("skills") or []) if str(s).strip()]
        cand_set = set(cand)
        blob = " ".join(cand)
        n = 0
        for kw in required:
            if kw in cand_set:
                n += 2
            elif kw in blob:
                n += 1
        return n

    def position_hits(r: dict[str, Any]) -> int:
        title = str(r.get("title", "")).lower()
        n = 0
        for pk in parsed_params.get("position_keywords") or []:
            p = str(pk).lower().strip()
            if p and p in title:
                n += 1
        return n

    def soft_signal_hits(r: dict[str, Any]) -> int:
        soft_signals = [
            str(s).lower().strip()
            for s in (parsed_params.get("soft_signals") or [])
            if str(s).strip()
        ]
        if not soft_signals:
            return 0
        blob = " ".join(
            [
                str(r.get("title", "")).lower(),
                " ".join(str(s).lower() for s in (r.get("skills") or [])),
                str(r.get("about", "")).lower(),
                str(r.get("raw_text", "")).lower(),
            ]
        )
        hits = sum(1 for signal in soft_signals if signal in blob)
        return min(3, hits)

    def match_source_weight(r: dict[str, Any]) -> int:
        source = str(r.get("match_source") or "")
        if source == "primary":
            return 3
        if source == "broad":
            return 1
        if source == "bonus":
            return -1
        return 0

    def sort_key(r: dict[str, Any]) -> tuple[int, float, int, int, str]:
        return (
            -match_source_weight(r),
            -exp_value(r),
            -skill_overlap(r),
            -soft_signal_hits(r),
            -position_hits(r),
            _resume_row_id(r) or "",
        )

    return sorted(resumes, key=sort_key)


async def _enrich_resumes_for_llm(
    resumes: list[dict[str, Any]],
    access_token: str | None,
    *,
    cache_user_id: uuid.UUID,
    max_enrich: int | None = None,
    db: Session | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    progress_phase: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    enriched: list[dict[str, Any] | None] = [None] * len(resumes)
    candidates_to_fetch: list[tuple[int, dict[str, Any], str]] = []
    max_fetch = max_enrich if max_enrich is not None else len(resumes)
    cache_hit = 0
    cache_miss = 0
    enrich_count = 0
    enrich_done = 0
    enrich_total = len(resumes)

    def _publish_enrich_progress() -> None:
        if progress_callback is None or not progress_phase:
            return
        progress_callback(
            {
                "stage": "enriching",
                "phase": progress_phase,
                "phase_total_count": enrich_total,
                "phase_done_count": enrich_done,
            }
        )

    for idx, r in enumerate(resumes):
        rid = _resume_row_id(r)
        if not rid:
            enriched[idx] = r
            enrich_done += 1
            _publish_enrich_progress()
            continue
        if r.get("work_experience") and r.get("about"):
            enriched[idx] = r
            enrich_done += 1
            _publish_enrich_progress()
            continue
        cached = resume_cache.get_cached_resume(cache_user_id, rid)
        if cached:
            cache_hit += 1
            enriched[idx] = {**r, **cached}
            enrich_done += 1
            _publish_enrich_progress()
            continue
        cache_miss += 1
        if enrich_count >= max_fetch:
            enriched[idx] = r
            enrich_done += 1
            _publish_enrich_progress()
            continue
        enrich_count += 1
        candidates_to_fetch.append((idx, r, rid))

    async def _fetch_one(idx: int, base_row: dict[str, Any], rid: str) -> None:
        nonlocal enrich_done
        try:
            full = await hh_client.fetch_resume(
                access_token,
                rid,
                db=db,
                hh_token_user_id=cache_user_id if db is not None else None,
            )
            resume_cache.cache_resume(cache_user_id, rid, full)
            enriched[idx] = {**base_row, **full}
        except HHClientError as e:
            # Лимит просмотров HH — фатальная ошибка для всего текущего запуска оценки.
            if is_daily_view_limit_error(e.detail):
                raise
            logger.warning("Не удалось подгрузить полное резюме %s: %s", rid, e)
            enriched[idx] = base_row
        except Exception as e:
            logger.warning("Не удалось подгрузить полное резюме %s: %s", rid, e)
            enriched[idx] = base_row
        finally:
            enrich_done += 1
            _publish_enrich_progress()

    if candidates_to_fetch:
        # Выполняем последовательно: после обнаружения лимита HH прекращаем дальнейшие fetch_resume.
        for idx, row, rid in candidates_to_fetch:
            await _fetch_one(idx, row, rid)

    out = [x if isinstance(x, dict) else resumes[i] for i, x in enumerate(enriched)]
    return out, {
        "cache_hit": cache_hit,
        "cache_miss": cache_miss,
        "hh_fetch_count": len(candidates_to_fetch),
    }


def _row_to_candidate_dict(
    merged: dict[str, Any],
    llm_score: int | None,
    *,
    store_skills: bool = True,
) -> dict[str, Any]:
    rid = _resume_row_id(merged)
    hh_url = merged.get("hh_resume_url")
    if hh_url is not None and not isinstance(hh_url, str):
        hh_url = str(hh_url) if hh_url else None
    if isinstance(hh_url, str):
        hh_url = hh_url.strip() or None
    skills: list[str] = (
        list(merged.get("skills") or []) if store_skills else []
    )
    st = merged.get("source_type") or "hh"
    if st != "hh":
        st = "hh"
    cpid = merged.get("candidate_profile_id")
    if cpid is not None:
        cpid = str(cpid).strip() or None
    out: dict[str, Any] = {
        "id": rid,
        "hh_resume_id": str(merged.get("hh_resume_id", "") or ""),
        "hh_resume_url": hh_url,
        "source_type": st,
        "candidate_profile_id": cpid,
        "source_resume_id": merged.get("source_resume_id"),
        "title": str(merged.get("title", "")),
        "full_name": str(merged.get("full_name", "")),
        "age": merged.get("age"),
        "experience_years": merged.get("experience_years"),
        "salary": merged.get("salary"),
        "skills": skills,
        "area": str(merged.get("area", "")),
        "work_experience": merged.get("work_experience"),
        "about": merged.get("about"),
        "education": merged.get("education"),
        "llm_score": llm_score,
        "llm_analysis": merged.get("llm_analysis"),
        "raw_text": merged.get("raw_text"),
        "normalized_payload": merged.get("normalized_payload"),
        "parse_confidence": merged.get("parse_confidence"),
        "parse_warnings": list(merged.get("parse_warnings") or []),
        "incompleteness_flags": list(merged.get("incompleteness_flags") or []),
        "match_source": str(merged.get("match_source") or ""),
    }
    if out["source_resume_id"] is not None:
        out["source_resume_id"] = str(out["source_resume_id"]).strip() or None
    if out["llm_analysis"] is not None and hasattr(out["llm_analysis"], "model_dump"):
        out["llm_analysis"] = out["llm_analysis"].model_dump(mode="json")
    return out


async def evaluate_all_resumes(
    access_token: str | None,
    resumes: list[dict[str, Any]],
    parsed_params: dict[str, Any],
    db: Session,
    *,
    user_id: uuid.UUID,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Выполняет pre-screening LLM по снимку кандидатов без подгрузки полных резюме,
    возвращает строки кандидатов с llm_score, отсортированные по убыванию балла.
    """
    if not resumes:
        return [], {
            "enrichment_elapsed_ms": 0,
            "prescore_elapsed_ms": 0,
            "interactive_elapsed_ms": 0,
            "background_elapsed_ms": 0,
            "interactive_scored_count": 0,
            "background_scored_count": 0,
            "interactive_llm_scored_count": 0,
            "background_llm_scored_count": 0,
            "interactive_fallback_count": 0,
            "background_fallback_count": 0,
            "llm_scored_count": 0,
            "fallback_scored_count": 0,
            "coverage_ratio": 1.0,
            "unresolved_count": 0,
            "interactive_unresolved_count": 0,
            "background_unresolved_count": 0,
            "llm_only_complete": True,
            "llm_calls_total": 0,
            "llm_calls_refill": 0,
            "avg_prompt_chars": 0,
            "parse_fail_count": 0,
            "refill_gain_ratio": 0.0,
            "prescore_mode": "chat_legacy",
            "rerank_calls_total": 0,
            "rerank_batch_split_count": 0,
            "rerank_avg_score": 0.0,
            "rerank_raw_avg_relevance": 0.0,
            "cache_hit": 0,
            "cache_miss": 0,
            "hh_fetch_count": 0,
            "status": "done",
        }

    sorted_resumes = _sort_by_simple_criteria(resumes, parsed_params)
    interactive_top_n = min(
        len(sorted_resumes),
        max(1, int(settings.evaluate_interactive_top_n or 50)),
    )
    interactive_rows = sorted_resumes[:interactive_top_n]
    background_rows = sorted_resumes[interactive_top_n:]

    def _phase_budget(raw_seconds: float | int | None) -> float | None:
        if raw_seconds is None:
            return None
        try:
            v = float(raw_seconds)
        except (TypeError, ValueError):
            return None
        # <= 0: отключаем time budget, чтобы оценка шла до полного покрытия/ошибки.
        return None if v <= 0 else max(1.0, v)

    async def _run_phase(
        phase: str,
        rows: list[dict[str, Any]],
        *,
        max_seconds: float | None,
    ) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
        if not rows:
            return [], {}, {
                "enrichment_elapsed_ms": 0,
                "prescore_elapsed_ms": 0,
                "llm_calls_total": 0,
                "llm_calls_refill": 0,
                "avg_prompt_chars": 0,
                "parse_fail_count": 0,
                "refill_gain_ratio": 0.0,
                "prescore_mode": "chat_legacy",
                "rerank_calls_total": 0,
                "rerank_batch_split_count": 0,
                "rerank_avg_score": 0.0,
                "rerank_raw_avg_relevance": 0.0,
                "cache_hit": 0,
                "cache_miss": 0,
                "hh_fetch_count": 0,
                "budget_exhausted": False,
                "llm_scored_count": 0,
                "fallback_scored_count": 0,
                "coverage_ratio": 1.0,
                "unresolved_count": 0,
                "recovery_batches_total": 0,
                "single_resume_attempts_total": 0,
                "single_resume_fail_count": 0,
                "llm_only_complete": True,
                "status": "done",
            }
        enriched_rows = rows
        enrich_stats = {"cache_hit": 0, "cache_miss": 0, "hh_fetch_count": 0}
        enrichment_elapsed_ms = 0
        max_enrich = int(settings.evaluate_max_enrich_resumes or 0)
        if max_enrich <= 0:
            max_enrich = len(rows) if phase == "interactive" else 0
        max_enrich = min(max_enrich, len(rows))
        if max_enrich > 0:
            enrich_started = time.monotonic()
            try:
                enriched_rows, enrich_stats = await _enrich_resumes_for_llm(
                    rows,
                    access_token,
                    cache_user_id=user_id,
                    max_enrich=max_enrich,
                    db=db,
                )
            except HHClientError as e:
                logger.warning(
                    "evaluate enrichment failed for phase=%s with HH error: %s",
                    phase,
                    e,
                )
                enriched_rows = rows
            except Exception as e:
                logger.warning(
                    "evaluate enrichment failed for phase=%s: %s",
                    phase,
                    e,
                )
                enriched_rows = rows
            enrichment_elapsed_ms = int((time.monotonic() - enrich_started) * 1000)
        prescore_rows = [_prescore_payload_from_row(r) for r in enriched_rows]
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "enrichment",
                    "phase": phase,
                    "event": "done",
                    "enriched_count": len(prescore_rows),
                    "total_count": len(rows),
                    "cache_hit": enrich_stats.get("cache_hit", 0),
                    "cache_miss": enrich_stats.get("cache_miss", 0),
                }
            )
        phase_scores, phase_prescore_stats = await asyncio.to_thread(
            llm_prescoring.prescore_resumes_batch,
            parsed_params,
            prescore_rows,
            db,
            progress_callback=progress_callback,
            phase=phase,
            max_seconds=max_seconds,
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "phase_done",
                    "phase": phase,
                    "phase_total_count": len(rows),
                    "phase_scored_count": len(phase_scores),
                    "phase_llm_scored_count": int(phase_prescore_stats.get("llm_scored_count") or 0),
                    "phase_fallback_count": int(phase_prescore_stats.get("fallback_scored_count") or 0),
                    "phase_coverage_ratio": float(phase_prescore_stats.get("coverage_ratio") or 0.0),
                    "phase_unresolved_count": int(phase_prescore_stats.get("unresolved_count") or 0),
                    "phase_llm_only_complete": bool(phase_prescore_stats.get("llm_only_complete")),
                    "budget_exhausted": bool(phase_prescore_stats.get("budget_exhausted")),
                }
            )
        merged_rows = [{**rows[i], **prescore_rows[i]} for i in range(len(rows))]
        unresolved_count = int(phase_prescore_stats.get("unresolved_count") or 0)
        llm_only_complete = bool(
            phase_prescore_stats.get("llm_only_complete")
            if phase_prescore_stats.get("llm_only_complete") is not None
            else unresolved_count == 0
        )
        return merged_rows, phase_scores, {
            "enrichment_elapsed_ms": enrichment_elapsed_ms,
            "prescore_elapsed_ms": int(phase_prescore_stats.get("prescore_elapsed_ms") or 0),
            "llm_calls_total": int(phase_prescore_stats.get("llm_calls_total") or 0),
            "llm_calls_refill": int(phase_prescore_stats.get("llm_calls_refill") or 0),
            "avg_prompt_chars": int(phase_prescore_stats.get("avg_prompt_chars") or 0),
            "parse_fail_count": int(phase_prescore_stats.get("parse_fail_count") or 0),
            "refill_gain_ratio": float(phase_prescore_stats.get("refill_gain_ratio") or 0.0),
            "prescore_mode": str(phase_prescore_stats.get("prescore_mode") or "chat_legacy"),
            "rerank_calls_total": int(phase_prescore_stats.get("rerank_calls_total") or 0),
            "rerank_batch_split_count": int(phase_prescore_stats.get("rerank_batch_split_count") or 0),
            "rerank_avg_score": float(phase_prescore_stats.get("rerank_avg_score") or 0.0),
            "rerank_raw_avg_relevance": float(phase_prescore_stats.get("rerank_raw_avg_relevance") or 0.0),
            "cache_hit": int(enrich_stats.get("cache_hit") or 0),
            "cache_miss": int(enrich_stats.get("cache_miss") or 0),
            "hh_fetch_count": int(enrich_stats.get("hh_fetch_count") or 0),
            "budget_exhausted": bool(phase_prescore_stats.get("budget_exhausted")),
            "llm_scored_count": int(phase_prescore_stats.get("llm_scored_count") or 0),
            "fallback_scored_count": int(phase_prescore_stats.get("fallback_scored_count") or 0),
            "coverage_ratio": float(phase_prescore_stats.get("coverage_ratio") or 0.0),
            "unresolved_count": unresolved_count,
            "recovery_batches_total": int(phase_prescore_stats.get("recovery_batches_total") or 0),
            "single_resume_attempts_total": int(phase_prescore_stats.get("single_resume_attempts_total") or 0),
            "single_resume_fail_count": int(phase_prescore_stats.get("single_resume_fail_count") or 0),
            "llm_only_complete": llm_only_complete,
            "status": str(phase_prescore_stats.get("status") or "done"),
        }

    interactive_started = time.monotonic()
    interactive_enriched, interactive_scores, interactive_stats = await _run_phase(
        "interactive",
        interactive_rows,
        max_seconds=_phase_budget(settings.llm_prescore_interactive_max_seconds),
    )
    interactive_elapsed_ms = int((time.monotonic() - interactive_started) * 1000)

    background_started = time.monotonic()
    background_enriched, background_scores, background_stats = await _run_phase(
        "background",
        background_rows,
        max_seconds=_phase_budget(settings.llm_prescore_background_max_seconds),
    )
    background_elapsed_ms = int((time.monotonic() - background_started) * 1000)

    logger.info(
        "evaluate phases: interactive_scored=%s/%s background_scored=%s/%s",
        len(interactive_scores),
        len(interactive_rows),
        len(background_scores),
        len(background_rows),
    )

    scores = {**interactive_scores, **background_scores}
    enriched = [*interactive_enriched, *background_enriched]

    merged_by_id: dict[str, dict[str, Any]] = {}
    for m in enriched:
        rid = _resume_row_id(m)
        if rid:
            merged_by_id[rid] = m

    rows: list[tuple[dict[str, Any], int]] = []
    for r in sorted_resumes:
        rid = _resume_row_id(r)
        merged = merged_by_id.get(rid, r)
        sc = scores.get(rid) if rid else None
        sort_key = int(sc) if sc is not None else -1
        rows.append(
            (_row_to_candidate_dict(merged, sc, store_skills=False), sort_key)
        )

    rows.sort(key=lambda t: (-t[1], t[0].get("id", "")))
    top_n_guard = min(len(rows), max(1, int(settings.search_bonus_guard_top_n or 30)))
    max_bonus_share = max(0.0, min(1.0, float(settings.search_bonus_share_max or 0.2)))
    if rows and max_bonus_share < 1.0:
        max_bonus = max(0, int(top_n_guard * max_bonus_share))
        picked_bonus = 0
        head: list[tuple[dict[str, Any], int]] = []
        overflow_bonus: list[tuple[dict[str, Any], int]] = []
        rest: list[tuple[dict[str, Any], int]] = []
        for row in rows:
            source = str(row[0].get("match_source") or "")
            if len(head) >= top_n_guard:
                rest.append(row)
            elif source == "bonus" and picked_bonus >= max_bonus:
                overflow_bonus.append(row)
            else:
                if source == "bonus":
                    picked_bonus += 1
                head.append(row)
        rows = head + overflow_bonus + rest
    coverage_ratio = float(len(scores) / len(sorted_resumes)) if sorted_resumes else 1.0
    unresolved_count = int(interactive_stats["unresolved_count"] + background_stats["unresolved_count"])
    llm_only_complete = bool(interactive_stats["llm_only_complete"] and background_stats["llm_only_complete"])
    if llm_only_complete:
        status = "done"
    elif len(scores) == 0 and len(sorted_resumes) > 0:
        status = "error"
    else:
        status = "partial"
    interactive_mode = str(interactive_stats["prescore_mode"])
    background_mode = str(background_stats["prescore_mode"])
    if interactive_mode == background_mode:
        prescore_mode = interactive_mode
    elif int(background_stats["llm_calls_total"]) == 0:
        prescore_mode = interactive_mode
    elif int(interactive_stats["llm_calls_total"]) == 0:
        prescore_mode = background_mode
    else:
        prescore_mode = "mixed"
    return [t[0] for t in rows], {
        "status": status,
        "enrichment_elapsed_ms": int(interactive_stats["enrichment_elapsed_ms"] + background_stats["enrichment_elapsed_ms"]),
        "prescore_elapsed_ms": int(interactive_stats["prescore_elapsed_ms"] + background_stats["prescore_elapsed_ms"]),
        "interactive_elapsed_ms": interactive_elapsed_ms,
        "background_elapsed_ms": background_elapsed_ms,
        "interactive_scored_count": len(interactive_scores),
        "background_scored_count": len(background_scores),
        "interactive_llm_scored_count": int(interactive_stats["llm_scored_count"]),
        "background_llm_scored_count": int(background_stats["llm_scored_count"]),
        "interactive_fallback_count": int(interactive_stats["fallback_scored_count"]),
        "background_fallback_count": int(background_stats["fallback_scored_count"]),
        "llm_scored_count": int(interactive_stats["llm_scored_count"] + background_stats["llm_scored_count"]),
        "fallback_scored_count": int(interactive_stats["fallback_scored_count"] + background_stats["fallback_scored_count"]),
        "coverage_ratio": round(coverage_ratio, 4),
        "unresolved_count": unresolved_count,
        "interactive_unresolved_count": int(interactive_stats["unresolved_count"]),
        "background_unresolved_count": int(background_stats["unresolved_count"]),
        "llm_only_complete": llm_only_complete,
        "llm_calls_total": int(interactive_stats["llm_calls_total"] + background_stats["llm_calls_total"]),
        "llm_calls_refill": int(interactive_stats["llm_calls_refill"] + background_stats["llm_calls_refill"]),
        "avg_prompt_chars": int(
            (
                interactive_stats["avg_prompt_chars"] + background_stats["avg_prompt_chars"]
            )
            / 2
        )
        if (interactive_stats["avg_prompt_chars"] or background_stats["avg_prompt_chars"])
        else 0,
        "parse_fail_count": int(interactive_stats["parse_fail_count"] + background_stats["parse_fail_count"]),
        "refill_gain_ratio": round(
            (
                float(interactive_stats["refill_gain_ratio"])
                + float(background_stats["refill_gain_ratio"])
            )
            / 2,
            4,
        ),
        "prescore_mode": prescore_mode,
        "rerank_calls_total": int(interactive_stats["rerank_calls_total"] + background_stats["rerank_calls_total"]),
        "rerank_batch_split_count": int(
            interactive_stats["rerank_batch_split_count"] + background_stats["rerank_batch_split_count"]
        ),
        "rerank_avg_score": round(
            (
                float(interactive_stats["rerank_avg_score"]) + float(background_stats["rerank_avg_score"])
            )
            / 2,
            4,
        ),
        "rerank_raw_avg_relevance": round(
            (
                float(interactive_stats["rerank_raw_avg_relevance"])
                + float(background_stats["rerank_raw_avg_relevance"])
            )
            / 2,
            6,
        ),
        "cache_hit": int(interactive_stats["cache_hit"] + background_stats["cache_hit"]),
        "cache_miss": int(interactive_stats["cache_miss"] + background_stats["cache_miss"]),
        "hh_fetch_count": int(interactive_stats["hh_fetch_count"] + background_stats["hh_fetch_count"]),
        "interactive_budget_exhausted": bool(interactive_stats["budget_exhausted"]),
        "background_budget_exhausted": bool(background_stats["budget_exhausted"]),
        "interactive_coverage_ratio": round(float(interactive_stats["coverage_ratio"]), 4),
        "background_coverage_ratio": round(float(background_stats["coverage_ratio"]), 4),
        "recovery_batches_total": int(interactive_stats["recovery_batches_total"] + background_stats["recovery_batches_total"]),
        "single_resume_attempts_total": int(
            interactive_stats["single_resume_attempts_total"] + background_stats["single_resume_attempts_total"]
        ),
        "single_resume_fail_count": int(
            interactive_stats["single_resume_fail_count"] + background_stats["single_resume_fail_count"]
        ),
    }


async def analyze_top_resumes(
    access_token: str | None,
    items: list[dict[str, Any]],
    parsed_params: dict[str, Any],
    *,
    user_id: str,
    query: str,
    top_n: int,
    db: Session,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Берёт топ-N по llm_score (нужна предварительная оценка), детальный LLM, кэш, обновление llm_analysis.
    """
    if not items:
        return [], {
            "detailed_total_ms": 0,
            "detailed_enrich_ms": 0,
            "detailed_analyze_ms": 0,
            "detailed_batch_count": 0,
            "detailed_batch_parse_fail_count": 0,
            "detailed_fallback_single_resume_count": 0,
            "detailed_prompt_chars_avg": 0,
            "detailed_prompt_chars_max": 0,
            "detailed_peak_concurrency": 0,
            "detailed_batch_size": 0,
            "detailed_analyze_concurrency": 0,
            "detailed_parse_fail_ratio": 0.0,
            "detailed_json_stability_ok": True,
            "hh_enrichment_cache_hit": 0,
            "hh_enrichment_cache_miss": 0,
            "hh_enrichment_fetch_count": 0,
            "hh_enrichment_share_ratio": 0.0,
            "hh_enrichment_optimization_recommended": False,
        }

    detailed_started = time.monotonic()
    cfg = llm_client.get_llm_config(db)
    n = max(1, min(50, int(top_n), int(cfg.llm_detailed_top_n or 15)))
    with_score = [(d, d.get("llm_score")) for d in items]
    with_score.sort(
        key=lambda x: (
            -(int(x[1]) if isinstance(x[1], int) else -1),
            _resume_row_id(x[0]),
        )
    )
    top = [x[0] for x in with_score[:n]]
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "start",
                "phase": "enriching",
                "processed_count": 0,
                "analyzed_count": 0,
                "total_count": len(top),
                "phase_total_count": len(top),
                "phase_done_count": 0,
                "enriched_count": 0,
            }
        )

    enrich_started = time.monotonic()
    enriched, enrich_stats = await _enrich_resumes_for_llm(
        top,
        access_token,
        cache_user_id=uuid.UUID(user_id),
        max_enrich=len(top),
        db=db,
        progress_callback=progress_callback,
        progress_phase="enriching",
    )
    detailed_enrich_ms = int((time.monotonic() - enrich_started) * 1000)
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "running",
                "phase": "analyzing",
                "processed_count": 0,
                "analyzed_count": 0,
                "total_count": len(top),
                "phase_total_count": len(top),
                "phase_done_count": 0,
                "enriched_count": len(enriched),
            }
        )
    batch_size = max(
        1, int(cfg.llm_search_batch_size or settings.llm_search_batch_size or 3)
    )
    analyze_concurrency = max(
        1,
        min(8, int(settings.llm_detailed_analyze_concurrency or 1)),
    )

    llm_by_id: dict[str, dict[str, Any]] = {}
    processed_count = 0
    detailed_batch_count = 0
    detailed_batch_parse_fail_count = 0
    detailed_fallback_single_resume_count = 0
    prompt_chars_sum = 0
    prompt_chars_samples = 0
    prompt_chars_max = 0
    active_workers = 0
    peak_concurrency = 0
    chunks = [enriched[i : i + batch_size] for i in range(0, len(enriched), batch_size)]
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(analyze_concurrency)
    analyze_started = time.monotonic()

    async def _analyze_chunk(chunk: list[dict[str, Any]]) -> None:
        nonlocal processed_count
        nonlocal detailed_batch_count
        nonlocal detailed_batch_parse_fail_count
        nonlocal detailed_fallback_single_resume_count
        nonlocal prompt_chars_sum
        nonlocal prompt_chars_samples
        nonlocal prompt_chars_max
        nonlocal active_workers
        nonlocal peak_concurrency
        async with semaphore:
            async with lock:
                active_workers += 1
                peak_concurrency = max(peak_concurrency, active_workers)
            try:
                batch_result = await asyncio.to_thread(
                    llm_resume_analyzer.analyze_resumes_batch,
                    parsed_params,
                    chunk,
                    batch_size=batch_size,
                    db=None,
                    runtime_config=cfg,
                    include_metrics=True,
                )
            finally:
                async with lock:
                    active_workers = max(0, active_workers - 1)
            if (
                isinstance(batch_result, tuple)
                and len(batch_result) == 2
                and isinstance(batch_result[0], dict)
                and isinstance(batch_result[1], dict)
            ):
                batch_out, batch_metrics = batch_result
            elif isinstance(batch_result, dict):
                batch_out = batch_result
                batch_metrics = {
                    "detailed_batch_count": 1 if len(chunk) > 1 else 0,
                }
            else:
                batch_out = {}
                batch_metrics = {}
            async with lock:
                detailed_batch_count += int(batch_metrics.get("detailed_batch_count") or 0)
                detailed_batch_parse_fail_count += int(
                    batch_metrics.get("detailed_batch_parse_fail_count") or 0
                )
                detailed_fallback_single_resume_count += int(
                    batch_metrics.get("detailed_fallback_single_resume_count") or 0
                )
                avg_chars = int(batch_metrics.get("detailed_prompt_chars_avg") or 0)
                max_chars = int(batch_metrics.get("detailed_prompt_chars_max") or 0)
                if max_chars > 0:
                    prompt_chars_samples += 1
                    prompt_chars_sum += avg_chars
                    prompt_chars_max = max(prompt_chars_max, max_chars)
                for r in chunk:
                    rid = _resume_row_id(r)
                    if not rid or rid not in batch_out:
                        continue
                    llm_by_id[rid] = batch_out[rid]
                    keys = llm_analysis_cache.resume_lookup_keys(r)
                    if not keys:
                        keys = [rid]
                    llm_analysis_cache.store_for_resume_ids(user_id, keys, query, batch_out[rid])
                    processed_count += 1
                    if progress_callback is not None:
                        progress_callback(
                            {
                                "stage": "running",
                                "phase": "analyzing",
                                "processed_count": processed_count,
                                "analyzed_count": len(llm_by_id),
                                "total_count": len(top),
                                "phase_total_count": len(top),
                                "phase_done_count": processed_count,
                                "analyses_delta": {rid: batch_out[rid]},
                            }
                        )

    await asyncio.gather(*[_analyze_chunk(chunk) for chunk in chunks])
    detailed_analyze_ms = int((time.monotonic() - analyze_started) * 1000)

    out: list[dict[str, Any]] = []
    for d in items:
        rid = _resume_row_id(d)
        row = dict(d)
        if rid and rid in llm_by_id:
            analysis = llm_by_id[rid]
            row["llm_analysis"] = analysis
            if isinstance(analysis.get("llm_score"), int):
                row["llm_score"] = analysis["llm_score"]
        out.append(row)
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "finalizing",
                "phase": "finalizing",
                "processed_count": processed_count,
                "analyzed_count": len(llm_by_id),
                "total_count": len(top),
                "phase_total_count": 1,
                "phase_done_count": 0,
            }
        )
        progress_callback(
            {
                "stage": "done",
                "phase": "done",
                "processed_count": processed_count,
                "analyzed_count": len(llm_by_id),
                "total_count": len(top),
                "phase_total_count": 1,
                "phase_done_count": 1,
            }
        )
    detailed_total_ms = int((time.monotonic() - detailed_started) * 1000)
    parse_fail_ratio = (
        float(detailed_batch_parse_fail_count) / float(detailed_batch_count)
        if detailed_batch_count > 0
        else 0.0
    )
    parse_fail_warn_ratio = max(
        0.0,
        min(1.0, float(settings.llm_detailed_parse_fail_warn_ratio or 0.25)),
    )
    detailed_json_stability_ok = parse_fail_ratio <= parse_fail_warn_ratio
    if not detailed_json_stability_ok:
        logger.warning(
            "Detailed analyze JSON stability degraded: parse_fail_ratio=%.3f threshold=%.3f",
            parse_fail_ratio,
            parse_fail_warn_ratio,
        )
    enrich_share_ratio = (
        float(detailed_enrich_ms) / float(detailed_total_ms)
        if detailed_total_ms > 0
        else 0.0
    )
    enrich_optimize_threshold = max(
        0.0,
        min(1.0, float(settings.llm_detailed_enrich_optimize_share_threshold or 0.35)),
    )
    hh_fetch_count = int(enrich_stats.get("hh_fetch_count") or 0)
    hh_enrichment_optimization_recommended = (
        hh_fetch_count > 0 and enrich_share_ratio >= enrich_optimize_threshold
    )
    metrics = {
        "detailed_total_ms": detailed_total_ms,
        "detailed_enrich_ms": detailed_enrich_ms,
        "detailed_analyze_ms": detailed_analyze_ms,
        "detailed_batch_count": detailed_batch_count,
        "detailed_batch_parse_fail_count": detailed_batch_parse_fail_count,
        "detailed_fallback_single_resume_count": detailed_fallback_single_resume_count,
        "detailed_prompt_chars_avg": int(prompt_chars_sum / prompt_chars_samples)
        if prompt_chars_samples > 0
        else 0,
        "detailed_prompt_chars_max": prompt_chars_max,
        "detailed_peak_concurrency": peak_concurrency,
        "detailed_batch_size": batch_size,
        "detailed_analyze_concurrency": analyze_concurrency,
        "detailed_parse_fail_ratio": round(parse_fail_ratio, 4),
        "detailed_json_stability_ok": detailed_json_stability_ok,
        "hh_enrichment_cache_hit": int(enrich_stats.get("cache_hit") or 0),
        "hh_enrichment_cache_miss": int(enrich_stats.get("cache_miss") or 0),
        "hh_enrichment_fetch_count": hh_fetch_count,
        "hh_enrichment_share_ratio": round(enrich_share_ratio, 4),
        "hh_enrichment_optimization_recommended": hh_enrichment_optimization_recommended,
    }
    return out, metrics
