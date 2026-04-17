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
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    enriched: list[dict[str, Any] | None] = [None] * len(resumes)
    candidates_to_fetch: list[tuple[int, dict[str, Any], str]] = []
    max_fetch = max_enrich if max_enrich is not None else len(resumes)
    cache_hit = 0
    cache_miss = 0
    enrich_count = 0

    for idx, r in enumerate(resumes):
        rid = _resume_row_id(r)
        if not rid:
            enriched[idx] = r
            continue
        if r.get("work_experience") and r.get("about"):
            enriched[idx] = r
            continue
        cached = resume_cache.get_cached_resume(cache_user_id, rid)
        if cached:
            cache_hit += 1
            enriched[idx] = {**r, **cached}
            continue
        cache_miss += 1
        if enrich_count >= max_fetch:
            enriched[idx] = r
            continue
        enrich_count += 1
        candidates_to_fetch.append((idx, r, rid))

    async def _fetch_one(idx: int, base_row: dict[str, Any], rid: str) -> None:
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
            "llm_calls_total": 0,
            "llm_calls_refill": 0,
            "avg_prompt_chars": 0,
            "parse_fail_count": 0,
            "refill_gain_ratio": 0.0,
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
    async def _run_phase(
        phase: str,
        rows: list[dict[str, Any]],
        *,
        max_seconds: float,
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
                "cache_hit": 0,
                "cache_miss": 0,
                "hh_fetch_count": 0,
                "budget_exhausted": False,
                "llm_scored_count": 0,
                "fallback_scored_count": 0,
                "coverage_ratio": 1.0,
            }
        stubs = [_candidate_stub_from_row(r) for r in rows]
        enriched_rows = stubs
        enrich_stats = {"cache_hit": 0, "cache_miss": 0, "hh_fetch_count": 0}
        enrichment_elapsed_ms = 0
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "enrichment",
                    "phase": phase,
                    "event": "done",
                    "enriched_count": len(enriched_rows),
                    "total_count": len(rows),
                    "cache_hit": enrich_stats.get("cache_hit", 0),
                    "cache_miss": enrich_stats.get("cache_miss", 0),
                }
            )
        phase_scores, phase_prescore_stats = await asyncio.to_thread(
            llm_prescoring.prescore_resumes_batch,
            parsed_params,
            enriched_rows,
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
                    "budget_exhausted": bool(phase_prescore_stats.get("budget_exhausted")),
                }
            )
        return enriched_rows, phase_scores, {
            "enrichment_elapsed_ms": enrichment_elapsed_ms,
            "prescore_elapsed_ms": int(phase_prescore_stats.get("prescore_elapsed_ms") or 0),
            "llm_calls_total": int(phase_prescore_stats.get("llm_calls_total") or 0),
            "llm_calls_refill": int(phase_prescore_stats.get("llm_calls_refill") or 0),
            "avg_prompt_chars": int(phase_prescore_stats.get("avg_prompt_chars") or 0),
            "parse_fail_count": int(phase_prescore_stats.get("parse_fail_count") or 0),
            "refill_gain_ratio": float(phase_prescore_stats.get("refill_gain_ratio") or 0.0),
            "cache_hit": int(enrich_stats.get("cache_hit") or 0),
            "cache_miss": int(enrich_stats.get("cache_miss") or 0),
            "hh_fetch_count": int(enrich_stats.get("hh_fetch_count") or 0),
            "budget_exhausted": bool(phase_prescore_stats.get("budget_exhausted")),
            "llm_scored_count": int(phase_prescore_stats.get("llm_scored_count") or 0),
            "fallback_scored_count": int(phase_prescore_stats.get("fallback_scored_count") or 0),
            "coverage_ratio": float(phase_prescore_stats.get("coverage_ratio") or 0.0),
        }

    interactive_started = time.monotonic()
    interactive_enriched, interactive_scores, interactive_stats = await _run_phase(
        "interactive",
        interactive_rows,
        max_seconds=max(1.0, float(settings.llm_prescore_interactive_max_seconds or 12.0)),
    )
    interactive_elapsed_ms = int((time.monotonic() - interactive_started) * 1000)

    background_started = time.monotonic()
    background_enriched, background_scores, background_stats = await _run_phase(
        "background",
        background_rows,
        max_seconds=max(1.0, float(settings.llm_prescore_background_max_seconds or 45.0)),
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
    status = "done" if coverage_ratio >= 1.0 else "partial"
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
        "cache_hit": int(interactive_stats["cache_hit"] + background_stats["cache_hit"]),
        "cache_miss": int(interactive_stats["cache_miss"] + background_stats["cache_miss"]),
        "hh_fetch_count": int(interactive_stats["hh_fetch_count"] + background_stats["hh_fetch_count"]),
        "interactive_budget_exhausted": bool(interactive_stats["budget_exhausted"]),
        "background_budget_exhausted": bool(background_stats["budget_exhausted"]),
        "interactive_coverage_ratio": round(float(interactive_stats["coverage_ratio"]), 4),
        "background_coverage_ratio": round(float(background_stats["coverage_ratio"]), 4),
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
) -> list[dict[str, Any]]:
    """
    Берёт топ-N по llm_score (нужна предварительная оценка), детальный LLM, кэш, обновление llm_analysis.
    """
    if not items:
        return []

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
                "processed_count": 0,
                "analyzed_count": 0,
                "total_count": len(top),
            }
        )

    enriched, _enrich_stats = await _enrich_resumes_for_llm(
        top,
        access_token,
        cache_user_id=uuid.UUID(user_id),
        max_enrich=len(top),
        db=db,
    )
    batch_size = max(1, int(cfg.llm_search_batch_size or 10))

    llm_by_id: dict[str, dict[str, Any]] = {}
    processed_count = 0
    for i in range(0, len(enriched), batch_size):
        chunk = enriched[i : i + batch_size]
        batch_out = await asyncio.to_thread(
            llm_resume_analyzer.analyze_resumes_batch,
            parsed_params,
            chunk,
            batch_size=batch_size,
            db=db,
        )
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
            batch_analyses = {
                _resume_row_id(r): batch_out[_resume_row_id(r)]
                for r in chunk
                if _resume_row_id(r) and _resume_row_id(r) in batch_out
            }
            progress_callback(
                {
                    "stage": "running",
                    "processed_count": processed_count,
                    "analyzed_count": len(llm_by_id),
                    "total_count": len(top),
                    "analyses_delta": batch_analyses,
                }
            )

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
                "stage": "done",
                "processed_count": processed_count,
                "analyzed_count": len(llm_by_id),
                "total_count": len(top),
            }
        )
    return out
