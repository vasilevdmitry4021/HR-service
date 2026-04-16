"""Быстрая числовая оценка резюме лёгкой моделью (pre-screening перед детальным анализом)."""

from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import settings
from app.services import llm_client
from app.services.llm_resume_analyzer import _format_resume_for_prescore_batch

logger = logging.getLogger(__name__)

PRESCORE_BATCH_PROMPT = """Ты — HR-скринер. По каждому резюме дай одну оценку соответствия требованиям (0–100).
Учитывай навыки, должность, опыт; синонимы и разные языки эквивалентны (Python = питон).

Требования:
- Должность: {position}
- Ключевые навыки: {skills}
- Минимальный опыт: {exp_min}
- Регион: {region}

Резюме (сжатый формат для быстрой оценки: должность, опыт, регион, фрагменты «о себе» и описаний работы):
{resumes_block}

Верни СТРОГО ТОЛЬКО JSON-массив (без markdown и комментариев), в том же порядке, что резюме в списке.
Длина массива должна совпадать с количеством резюме.
Каждый элемент: {{"resume_id": "<id из списка>", "score": <целое 0-100>}}
Если сомневаешься, все равно верни приблизительный целый score.
Формат ответа:
[{{"resume_id": "<id1>", "score": 73}}, {{"resume_id": "<id2>", "score": 41}}]"""


def _format_prescore_header(requirements: dict[str, Any]) -> dict[str, str]:
    exp = requirements.get("experience_years_min")
    exp_str = f"от {exp} лет" if exp is not None else "не указан"
    return {
        "position": ", ".join(requirements.get("position_keywords") or []) or "не указана",
        "skills": ", ".join(requirements.get("skills") or []) or "не указаны",
        "exp_min": exp_str,
        "region": str(requirements.get("region") or "любой"),
    }


def _call_llm_raw_with_model(
    user_prompt: str,
    model: str,
    timeout: float = 180.0,
    *,
    use_json_constraint: bool = True,
    db: Session | None = None,
) -> str | None:
    if not llm_client.llm_connection_configured(db):
        return None
    m = (model or llm_client.get_llm_config(db).model or "llama3.2").strip()
    return llm_client.call_llm_user_prompt(
        db,
        user_prompt,
        model=m,
        format_json=use_json_constraint,
        timeout=timeout,
    )


def _parse_score(item: dict[str, Any]) -> int | None:
    raw = item.get("score", item.get("prescore_score", item.get("llm_score")))
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0, min(100, int(raw)))
    try:
        return max(0, min(100, int(float(str(raw).strip()))))
    except (TypeError, ValueError):
        return None


def _slice_balanced_json_array(s: str) -> str | None:
    """Вырезает первый корректный JSON-массив по скобкам (с учётом строк)."""
    i = s.find("[")
    if i < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(s)):
        c = s[j]
        if esc:
            esc = False
            continue
        if c == "\\" and in_str:
            esc = True
            continue
        if c == '"' and not esc:
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return s[i : j + 1]
    return None


def _coerce_prescore_payload(data: Any) -> list[dict[str, Any]] | None:
    """Превращает ответ LLM в список объектов с оценками."""
    if isinstance(data, list):
        out = [x for x in data if isinstance(x, dict)]
        return out if out else None
    if isinstance(data, dict):
        for k in (
            "scores",
            "results",
            "items",
            "data",
            "evaluations",
            "resumes",
            "candidates",
        ):
            v = data.get(k)
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return [x for x in v if isinstance(x, dict)]
        if any(k in data for k in ("score", "resume_id", "id", "llm_score")):
            return [data]
    return None


def _parse_prescore_llm_text(raw: str | None) -> list[dict[str, Any]] | None:
    """Разбор текста ответа: массив, объект-обёртка, markdown, мусор до/после JSON."""
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()

    def _try_load(s: str) -> list[dict[str, Any]] | None:
        try:
            data = json.loads(s)
        except json.JSONDecodeError:
            return None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                return None
        return _coerce_prescore_payload(data)

    parsed = _try_load(text)
    if parsed:
        return parsed

    sliced = _slice_balanced_json_array(text)
    if sliced:
        parsed = _try_load(sliced)
        if parsed:
            return parsed

    return None


def _resume_id_from_item(item: dict[str, Any]) -> str:
    for k in ("resume_id", "id", "hh_resume_id", "resumeId"):
        v = item.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return ""


def _scores_from_array_for_chunk(
    arr: list[dict[str, Any]],
    chunk: list[dict[str, Any]],
    rid_of,
) -> dict[str, int]:
    """Сопоставляет ответ LLM со строками батча: по полям id и по позиции (частичный массив)."""
    by_id: dict[str, int] = {}
    explicit_id_count = 0
    for item in arr:
        if not isinstance(item, dict):
            continue
        rid = _resume_id_from_item(item)
        sc = _parse_score(item)
        if rid and sc is not None:
            explicit_id_count += 1
            by_id[rid] = sc

    use_positional_fallback = explicit_id_count < len(arr)
    n = min(len(arr), len(chunk))
    for i in range(n):
        if not use_positional_fallback:
            break
        k = rid_of(chunk[i])
        if not k:
            continue
        it = arr[i]
        if not isinstance(it, dict):
            continue
        if _resume_id_from_item(it):
            continue
        sc = _parse_score(it)
        if sc is not None:
            by_id[k] = sc

    return {k: by_id[k] for k in (rid_of(r) for r in chunk) if k and k in by_id}


def _fetch_prescore_array(
    prompt: str,
    model: str,
    *,
    batch_label: str,
    db: Session | None = None,
) -> tuple[list[dict[str, Any]] | None, int, str]:
    retry_count = 0
    fail_reason = "parse-fail"
    try:
        raw = _call_llm_raw_with_model(
            prompt,
            model,
            timeout=240.0,
            use_json_constraint=True,
            db=db,
        )
    except Exception as exc:
        text = str(exc).lower()
        fail_reason = "timeout" if ("timeout" in text or isinstance(exc, TimeoutError)) else "parse-fail"
        logger.warning("pre-screening: ошибка LLM (%s): %s", batch_label, exc)
        raw = None
    arr = _parse_prescore_llm_text(raw)
    raw_loose: str | None = None
    if not arr:
        retry_count += 1
        try:
            raw_loose = _call_llm_raw_with_model(
                prompt,
                model,
                timeout=240.0,
                use_json_constraint=False,
                db=db,
            )
        except Exception as exc:
            text = str(exc).lower()
            fail_reason = "timeout" if ("timeout" in text or isinstance(exc, TimeoutError)) else fail_reason
            logger.warning("pre-screening: ошибка LLM (loose, %s): %s", batch_label, exc)
            raw_loose = None
        arr = _parse_prescore_llm_text(raw_loose)
    if not arr:
        preview_src = raw_loose if raw_loose else raw
        preview = (
            (preview_src[:500] + "…")
            if preview_src and len(preview_src) > 500
            else (preview_src or "")
        )
        logger.warning(
            "pre-screening: не удалось разобрать ответ LLM (%s), превью: %s",
            batch_label,
            preview,
        )
    return arr, retry_count, fail_reason


def _norm_text(v: Any) -> str:
    text = str(v or "").strip().lower()
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text)


def _tokenize(v: Any) -> list[str]:
    text = _norm_text(v)
    if not text:
        return []
    return [x for x in re.split(r"[^a-zа-я0-9+#]+", text) if x]


def _to_float(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _fallback_score_for_resume(requirements: dict[str, Any], resume: dict[str, Any]) -> int:
    min_score = int(settings.llm_prescore_fallback_min_score or 0)
    max_score = int(settings.llm_prescore_fallback_max_score or 100)
    if min_score > max_score:
        min_score, max_score = max_score, min_score
    w_skills = max(0.0, float(settings.llm_prescore_fallback_weight_skills or 0.4))
    w_pos = max(0.0, float(settings.llm_prescore_fallback_weight_position or 0.25))
    w_exp = max(0.0, float(settings.llm_prescore_fallback_weight_experience or 0.2))
    w_region = max(0.0, float(settings.llm_prescore_fallback_weight_region or 0.15))
    total_w = w_skills + w_pos + w_exp + w_region
    if total_w <= 0:
        return max(min_score, min(100, max_score))

    req_skills = [_norm_text(s) for s in (requirements.get("skills") or []) if _norm_text(s)]
    resume_skills = [_norm_text(s) for s in (resume.get("skills") or []) if _norm_text(s)]
    resume_blob = " ".join(resume_skills)
    matched = 0
    for sk in req_skills:
        if sk in resume_skills or (sk and sk in resume_blob):
            matched += 1
    skills_part = (matched / len(req_skills)) if req_skills else 0.5

    title = _norm_text(resume.get("title"))
    req_pos = [_norm_text(s) for s in (requirements.get("position_keywords") or []) if _norm_text(s)]
    if req_pos:
        pos_hits = sum(1 for kw in req_pos if kw in title)
        position_part = pos_hits / len(req_pos)
    else:
        position_part = 0.5

    req_exp = _to_float(requirements.get("experience_years_min"))
    cand_exp = _to_float(resume.get("experience_years"))
    if req_exp is None or req_exp <= 0:
        experience_part = 0.5
    elif cand_exp is None:
        experience_part = 0.2
    else:
        experience_part = max(0.0, min(1.0, cand_exp / req_exp))

    req_region = _norm_text(requirements.get("region"))
    area = _norm_text(resume.get("area"))
    if not req_region or req_region in {"любой", "any"}:
        region_part = 0.5
    elif req_region in area or area in req_region:
        region_part = 1.0
    else:
        req_tokens = set(_tokenize(req_region))
        area_tokens = set(_tokenize(area))
        overlap = len(req_tokens & area_tokens)
        region_part = (overlap / len(req_tokens)) if req_tokens else 0.0

    weighted_part = (
        skills_part * w_skills
        + position_part * w_pos
        + experience_part * w_exp
        + region_part * w_region
    ) / total_w
    raw = int(round(min_score + (max_score - min_score) * weighted_part))
    return max(0, min(100, max(min_score, min(max_score, raw))))


def _fill_missing_scores(
    requirements: dict[str, Any],
    resumes: list[dict[str, Any]],
    scores: dict[str, int],
    *,
    rid_of: Callable[[dict[str, Any]], str],
    phase: str,
    fallback_reason_by_id: dict[str, str],
    progress_callback: Callable[[dict[str, Any]], None] | None,
) -> tuple[dict[str, int], dict[str, int], int]:
    out = dict(scores)
    fallback_scores: dict[str, int] = {}
    reason_counts = {"parse-fail": 0, "timeout": 0, "limit-exhausted": 0}
    for row in resumes:
        rid = rid_of(row)
        if not rid or rid in out:
            continue
        reason = fallback_reason_by_id.get(rid, "limit-exhausted")
        if reason not in reason_counts:
            reason = "limit-exhausted"
        reason_counts[reason] += 1
        sc = _fallback_score_for_resume(requirements, row)
        out[rid] = sc
        fallback_scores[rid] = sc
        logger.info("pre-screening fallback: phase=%s resume_id=%s reason=%s score=%s", phase, rid, reason, sc)
    if fallback_scores and progress_callback is not None:
        progress_callback(
            {
                "stage": "prescore",
                "event": "fallback_done",
                "phase": phase,
                "scored_count": len(out),
                "fallback_scored_count": len(fallback_scores),
                "llm_scored_count": len(scores),
                "total_count": len(resumes),
                "scores_delta": dict(fallback_scores),
            }
        )
    return out, reason_counts, len(fallback_scores)


def prescore_resumes_batch(
    requirements: dict[str, Any],
    resumes: list[dict[str, Any]],
    db: Session | None = None,
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    phase: str = "interactive",
    max_seconds: float | None = None,
) -> tuple[dict[str, int], dict[str, Any]]:
    """
    Возвращает словарь resume_id -> оценка 0–100 только из ответа LLM.
    Без endpoint, при ошибке или пустом ответе — пустой словарь (или только то, что удалось разобрать).
    """
    if not resumes:
        return {}, {
            "prescore_elapsed_ms": 0,
            "llm_calls_total": 0,
            "llm_calls_refill": 0,
            "avg_prompt_chars": 0,
            "parse_fail_count": 0,
            "refill_gain_ratio": 0.0,
            "budget_exhausted": False,
            "llm_scored_count": 0,
            "fallback_scored_count": 0,
            "coverage_ratio": 1.0,
            "fallback_parse_fail_count": 0,
            "fallback_timeout_count": 0,
            "fallback_limit_exhausted_count": 0,
        }

    def rid_of(r: dict[str, Any]) -> str:
        return str(r.get("id", r.get("hh_resume_id", "")))

    out: dict[str, int] = {}
    t0 = time.monotonic()
    llm_calls_total = 0
    llm_calls_refill = 0
    prompt_chars_total = 0
    prompt_count = 0
    parse_fail_count = 0
    refill_gain_total = 0
    refill_attempted_total = 0
    budget_exhausted = False
    fallback_reason_by_id: dict[str, str] = {}

    cfg = llm_client.get_llm_config(db)
    llm_enabled = bool((cfg.endpoint or "").strip())

    model = (cfg.fast_model or cfg.model or "qwen2.5:7b").strip()
    base_batch_size = max(1, min(50, int(cfg.llm_fast_batch_size or 5)))
    batch_size = base_batch_size
    refill_batch_size = max(1, min(20, int(settings.llm_prescore_refill_batch_size or 5)))
    refill_time_limit_s = max(
        1.0,
        float(settings.llm_prescore_refill_max_seconds or 30.0),
    )
    budget_seconds = float(max_seconds) if max_seconds is not None else None
    refill_min_gain = max(0, int(settings.llm_prescore_refill_min_gain or 0))
    refill_low_gain_stop_cycles = 3
    header = _format_prescore_header(requirements)

    total_batches = max(1, (len(resumes) + max(1, batch_size) - 1) // max(1, batch_size))
    start = 0
    batch_idx = 0
    consecutive_parse_fail = 0
    while start < len(resumes):
        chunk = resumes[start : start + batch_size]
        chunk_start = start
        start += len(chunk)
        if not llm_enabled:
            for row in chunk:
                rid = rid_of(row)
                if rid:
                    fallback_reason_by_id[rid] = "limit-exhausted"
            continue
        if budget_seconds is not None and (time.monotonic() - t0) >= budget_seconds:
            budget_exhausted = True
            for row in chunk:
                rid = rid_of(row)
                if rid and rid not in out:
                    fallback_reason_by_id[rid] = "limit-exhausted"
            continue
        batch_idx += 1
        batch_started = time.monotonic()
        resumes_block = "\n".join(_format_resume_for_prescore_batch(r) for r in chunk)
        prompt = PRESCORE_BATCH_PROMPT.format(**header, resumes_block=resumes_block)
        prompt_chars_total += len(prompt)
        prompt_count += 1
        arr, retry_count, fail_reason = _fetch_prescore_array(
            prompt,
            model,
            batch_label=f"батч {chunk_start}..{chunk_start + len(chunk) - 1}",
            db=db,
        )
        llm_calls_total += 1 + retry_count
        if not arr:
            parse_fail_count += 1
            consecutive_parse_fail += 1
            for row in chunk:
                rid = rid_of(row)
                if rid and rid not in out:
                    fallback_reason_by_id[rid] = fail_reason
            if consecutive_parse_fail >= 2 and batch_size > 1:
                batch_size = max(1, batch_size // 2)
            logger.info(
                "pre-screening batch: phase=%s batch_index=%s/%s batch_size=%s missing_scores=%s retry_count=%s elapsed_ms=%s",
                phase,
                batch_idx,
                total_batches,
                len(chunk),
                len(chunk),
                retry_count,
                int((time.monotonic() - batch_started) * 1000),
            )
            continue
        consecutive_parse_fail = 0
        chunk_scores = _scores_from_array_for_chunk(arr, chunk, rid_of)
        out.update(chunk_scores)
        missing_scores = max(0, len(chunk) - len(chunk_scores))
        for row in chunk:
            rid = rid_of(row)
            if rid and rid not in chunk_scores and rid not in out:
                fallback_reason_by_id.setdefault(rid, "limit-exhausted")
        missing_ratio = float(missing_scores / len(chunk)) if chunk else 0.0
        if missing_ratio >= 0.5 and batch_size > 1:
            batch_size = max(1, batch_size // 2)
        elif missing_ratio <= 0.1 and batch_size < base_batch_size:
            batch_size += 1
        logger.info(
            "pre-screening batch: phase=%s batch_index=%s/%s batch_size=%s missing_scores=%s retry_count=%s elapsed_ms=%s",
            phase,
            batch_idx,
            total_batches,
            len(chunk),
            missing_scores,
            retry_count,
            int((time.monotonic() - batch_started) * 1000),
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "prescore",
                    "event": "batch_done",
                    "batch_index": batch_idx,
                    "total_batches": total_batches,
                    "batch_size": len(chunk),
                    "missing_scores": missing_scores,
                    "scored_count": len(out),
                    "llm_scored_count": len(out),
                    "fallback_scored_count": 0,
                    "total_count": len(resumes),
                    "retry_count": retry_count,
                    "scores_delta": dict(chunk_scores),
                    "phase": phase,
                }
            )

    if settings.llm_prescore_refill_enabled and llm_enabled:
        max_refill = max(0, int(settings.llm_prescore_refill_max_llm_calls or 0))
        refill_calls = 0
        refill_started = time.monotonic()
        low_gain_streak = 0
        while refill_calls < max_refill:
            if budget_seconds is not None and (time.monotonic() - t0) >= budget_seconds:
                budget_exhausted = True
                for row in resumes:
                    rid = rid_of(row)
                    if rid and rid not in out:
                        fallback_reason_by_id.setdefault(rid, "limit-exhausted")
                break
            if (time.monotonic() - refill_started) >= refill_time_limit_s:
                logger.warning(
                    "pre-screening refill остановлен по лимиту времени: elapsed_ms=%s limit_seconds=%s",
                    int((time.monotonic() - refill_started) * 1000),
                    refill_time_limit_s,
                )
                break
            missing = [
                r
                for r in resumes
                if rid_of(r) and rid_of(r) not in out
            ]
            if not missing:
                break
            refill_chunk = missing[:refill_batch_size]
            refill_attempted_total += len(refill_chunk)
            refill_batch_started = time.monotonic()
            resumes_block = "\n".join(
                _format_resume_for_prescore_batch(r) for r in refill_chunk
            )
            prompt = PRESCORE_BATCH_PROMPT.format(
                **header,
                resumes_block=resumes_block,
            )
            prompt_chars_total += len(prompt)
            prompt_count += 1
            arr, retry_count, fail_reason = _fetch_prescore_array(
                prompt,
                model,
                batch_label=f"refill {refill_calls + 1}, size={len(refill_chunk)}",
                db=db,
            )
            refill_calls += 1 + retry_count
            llm_calls_total += 1 + retry_count
            llm_calls_refill += 1 + retry_count
            if not arr:
                parse_fail_count += 1
                low_gain_streak += 1
                for row in refill_chunk:
                    rid = rid_of(row)
                    if rid and rid not in out:
                        fallback_reason_by_id[rid] = fail_reason
                logger.info(
                    "pre-screening refill: phase=%s chunk_size=%s missing_scores=%s retry_count=%s elapsed_ms=%s",
                    phase,
                    len(refill_chunk),
                    len(refill_chunk),
                    retry_count,
                    int((time.monotonic() - refill_batch_started) * 1000),
                )
                if low_gain_streak >= refill_low_gain_stop_cycles:
                    break
                continue
            chunk_scores = _scores_from_array_for_chunk(arr, refill_chunk, rid_of)
            refill_gain = len(chunk_scores)
            refill_gain_total += refill_gain
            if refill_gain < refill_min_gain:
                low_gain_streak += 1
            else:
                low_gain_streak = 0
            out.update(chunk_scores)
            missing_scores = max(0, len(refill_chunk) - len(chunk_scores))
            logger.info(
                "pre-screening refill: phase=%s chunk_size=%s missing_scores=%s retry_count=%s elapsed_ms=%s",
                phase,
                len(refill_chunk),
                missing_scores,
                retry_count,
                int((time.monotonic() - refill_batch_started) * 1000),
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "prescore",
                        "event": "refill_done",
                        "batch_size": len(refill_chunk),
                        "missing_scores": missing_scores,
                        "scored_count": len(out),
                        "llm_scored_count": len(out),
                        "fallback_scored_count": 0,
                        "total_count": len(resumes),
                        "retry_count": retry_count,
                        "llm_calls_refill": llm_calls_refill,
                        "scores_delta": dict(chunk_scores),
                        "phase": phase,
                    }
                )
            if low_gain_streak >= refill_low_gain_stop_cycles:
                logger.info(
                    "pre-screening refill остановлен по низкой эффективности: phase=%s refill_gain=%s min_gain=%s streak=%s",
                    phase,
                    refill_gain,
                    refill_min_gain,
                    low_gain_streak,
                )
                break

        still = sum(
            1 for r in resumes if rid_of(r) and rid_of(r) not in out
        )
        if still:
            logger.warning(
                "pre-screening: без числовой оценки осталось резюме: %s (из %s)",
                still,
                len(resumes),
            )
            for r in resumes:
                rid = rid_of(r)
                if rid and rid not in out:
                    fallback_reason_by_id.setdefault(rid, "limit-exhausted")

    llm_scored_count = len(out)
    fallback_scored_count = 0
    fallback_reasons = {"parse-fail": 0, "timeout": 0, "limit-exhausted": 0}
    if settings.llm_prescore_enable_fallback:
        out, fallback_reasons, fallback_scored_count = _fill_missing_scores(
            requirements,
            resumes,
            out,
            rid_of=rid_of,
            phase=phase,
            fallback_reason_by_id=fallback_reason_by_id,
            progress_callback=progress_callback,
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    avg_prompt_chars = int(prompt_chars_total / prompt_count) if prompt_count else 0
    refill_gain_ratio = (
        float(refill_gain_total / refill_attempted_total)
        if refill_attempted_total > 0
        else 0.0
    )
    coverage_ratio = float(len(out) / len(resumes)) if resumes else 1.0
    return out, {
        "prescore_elapsed_ms": elapsed_ms,
        "llm_calls_total": llm_calls_total,
        "llm_calls_refill": llm_calls_refill,
        "avg_prompt_chars": avg_prompt_chars,
        "parse_fail_count": parse_fail_count,
        "refill_gain_ratio": round(refill_gain_ratio, 4),
        "budget_exhausted": budget_exhausted,
        "llm_scored_count": llm_scored_count,
        "fallback_scored_count": fallback_scored_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "fallback_parse_fail_count": int(fallback_reasons["parse-fail"]),
        "fallback_timeout_count": int(fallback_reasons["timeout"]),
        "fallback_limit_exhausted_count": int(fallback_reasons["limit-exhausted"]),
    }
