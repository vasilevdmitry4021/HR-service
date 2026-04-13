"""Синхронная оценка снимка поиска: pre-screening и детальный анализ топ-N."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.services import hh_client
from app.services import llm_client
from app.services import llm_analysis_cache
from app.services import llm_prescoring
from app.services import llm_resume_analyzer
from app.services import resume_cache

logger = logging.getLogger(__name__)


def _resume_row_id(d: dict[str, Any]) -> str:
    return str(d.get("id", d.get("hh_resume_id", "")))


def _candidate_stub_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Для Telegram передаётся полный снимок профиля — модели нужны raw_text и нормализация."""
    if row.get("source_type") == "telegram":
        return dict(row)
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

    def sort_key(r: dict[str, Any]) -> tuple[float, int, int, str]:
        return (
            -exp_value(r),
            -skill_overlap(r),
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
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    enrich_count = 0
    for r in resumes:
        if r.get("source_type") == "telegram":
            enriched.append(dict(r))
            continue
        rid = _resume_row_id(r)
        if not rid:
            enriched.append(r)
            continue
        if r.get("work_experience") and r.get("about"):
            enriched.append(r)
            continue
        cached = resume_cache.get_cached_resume(cache_user_id, rid)
        if cached:
            enriched.append({**r, **cached})
            continue
        if max_enrich is not None and enrich_count >= max_enrich:
            enriched.append(r)
            continue
        try:
            full = await hh_client.fetch_resume(
                access_token,
                rid,
                db=db,
                hh_token_user_id=cache_user_id if db is not None else None,
            )
            resume_cache.cache_resume(cache_user_id, rid, full)
            enriched.append({**r, **full})
            enrich_count += 1
        except Exception as e:
            logger.warning("Не удалось подгрузить полное резюме %s: %s", rid, e)
            enriched.append(r)
    return enriched


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
    if st not in ("hh", "telegram"):
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
        "telegram_sources": [
            x
            for x in (merged.get("telegram_sources") or [])
            if isinstance(x, dict)
        ],
        "telegram_attachments": [
            x
            for x in (merged.get("telegram_attachments") or [])
            if isinstance(x, dict)
        ],
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
) -> list[dict[str, Any]]:
    """
    Подгружает полные резюме (о себе, опыт), вызывает pre-screening LLM батчами,
    возвращает строки кандидатов с llm_score, отсортированные по убыванию балла.
    """
    if not resumes:
        return []

    sorted_resumes = _sort_by_simple_criteria(resumes, parsed_params)
    max_to_enrich = min(
        max(0, int(settings.evaluate_max_enrich_resumes)),
        len(sorted_resumes),
    )
    head = sorted_resumes[:max_to_enrich]
    stubs_head = [_candidate_stub_from_row(r) for r in head]
    enriched = await _enrich_resumes_for_llm(
        stubs_head,
        access_token,
        cache_user_id=user_id,
        max_enrich=max_to_enrich,
        db=db,
    )
    scores = llm_prescoring.prescore_resumes_batch(parsed_params, enriched, db=db)

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
    return [t[0] for t in rows]


async def analyze_top_resumes(
    access_token: str | None,
    items: list[dict[str, Any]],
    parsed_params: dict[str, Any],
    *,
    user_id: str,
    query: str,
    top_n: int,
    db: Session,
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

    enriched = await _enrich_resumes_for_llm(
        top,
        access_token,
        cache_user_id=uuid.UUID(user_id),
        max_enrich=len(top),
        db=db,
    )
    batch_size = max(1, int(cfg.llm_search_batch_size or 10))

    llm_by_id: dict[str, dict[str, Any]] = {}
    for i in range(0, len(enriched), batch_size):
        chunk = enriched[i : i + batch_size]
        batch_out = llm_resume_analyzer.analyze_resumes_batch(
            parsed_params, chunk, batch_size=batch_size, db=db
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
    return out
