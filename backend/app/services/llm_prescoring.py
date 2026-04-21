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

PRESCORE_BATCH_PROMPT = """Ты — HR-скринер. Для каждого резюме дай ОДИН числовой score соответствия требованиям (0–100).
Это быстрый pre-screening: объяснения, strengths/gaps и любые дополнительные поля не нужны.
Главный фактор — совпадение ключевых навыков и релевантного опыта из semantic summary.
Оценивай не только теги навыков, но и задачи/проекты, домен, стек, контекст последних ролей.
Небольшие расхождения по числам (опыт, регион) не обнуляют score, если роль и стек релевантны.

Требования:
- Должность: {position}
- Ключевые навыки: {skills}
- Минимальный опыт: {exp_min}
- Регион: {region}
- Бонусные сигналы: {soft_signals}

Резюме (compact payload + semantic summary):
{resumes_block}

Верни СТРОГО ТОЛЬКО JSON-массив (без markdown и комментариев), в том же порядке, что резюме в списке.
Длина массива должна совпадать с количеством резюме.
Каждый элемент: {{"resume_id": "<id из списка>", "score": <целое 0-100>}}
Никаких дополнительных ключей. Если сомневаешься, все равно верни приблизительный целый score.
Формат ответа:
[{{"resume_id": "<id1>", "score": 73}}, {{"resume_id": "<id2>", "score": 41}}]"""


def _format_prescore_header(requirements: dict[str, Any]) -> dict[str, str]:
    exp = requirements.get("experience_years_min")
    exp_str = f"от {exp} лет" if exp is not None else "не указан"
    soft_signals = requirements.get("soft_signals")
    soft_text = ", ".join(str(s).strip() for s in (soft_signals or []) if str(s).strip())
    return {
        "position": ", ".join(requirements.get("position_keywords") or []) or "не указана",
        "skills": ", ".join(requirements.get("skills") or []) or "не указаны",
        "exp_min": exp_str,
        "region": str(requirements.get("region") or "любой"),
        "soft_signals": soft_text or "нет",
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


def _resume_text_blob(resume: dict[str, Any]) -> str:
    work_items = resume.get("work_experience") or []
    work_parts: list[str] = []
    for item in work_items:
        if not isinstance(item, dict):
            continue
        for key in ("position", "company", "description"):
            value = _norm_text(item.get(key))
            if value:
                work_parts.append(value)
    return " ".join(
        x
        for x in (
            _norm_text(resume.get("title")),
            " ".join(_norm_text(x) for x in (resume.get("skills") or []) if _norm_text(x)),
            _norm_text(resume.get("about")),
            _norm_text(resume.get("raw_text")),
            " ".join(work_parts),
        )
        if x
    )


def _skill_variants(requirements: dict[str, Any], skill: str) -> set[str]:
    normalized = _norm_text(skill)
    return {normalized} if normalized else set()


def _skills_part(requirements: dict[str, Any], resume: dict[str, Any]) -> float:
    req_skills = [_norm_text(s) for s in (requirements.get("skills") or []) if _norm_text(s)]
    if not req_skills:
        return 0.5
    resume_skills = {_norm_text(s) for s in (resume.get("skills") or []) if _norm_text(s)}
    resume_skill_blob = " ".join(sorted(resume_skills))
    resume_text_blob = _resume_text_blob(resume)
    matched_score = 0.0
    for skill in req_skills:
        variants = _skill_variants(requirements, skill)
        if any(variant in resume_skills for variant in variants):
            matched_score += 1.0
        elif any(variant and variant in resume_skill_blob for variant in variants):
            matched_score += 0.85
        elif any(variant and variant in resume_text_blob for variant in variants):
            matched_score += 0.65
    return max(0.0, min(1.0, matched_score / len(req_skills)))


def _position_part(requirements: dict[str, Any], resume: dict[str, Any]) -> float:
    req_pos = [_norm_text(s) for s in (requirements.get("position_keywords") or []) if _norm_text(s)]
    if not req_pos:
        return 0.5
    title = _norm_text(resume.get("title"))
    blob = _resume_text_blob(resume)
    hits = 0.0
    for keyword in req_pos:
        if keyword and keyword in title:
            hits += 1.0
        elif keyword and keyword in blob:
            hits += 0.6
    return max(0.0, min(1.0, hits / len(req_pos)))


def _experience_part(requirements: dict[str, Any], resume: dict[str, Any]) -> float:
    req_exp = _to_float(requirements.get("experience_years_min"))
    cand_exp = _to_float(resume.get("experience_years"))
    if req_exp is None or req_exp <= 0:
        return 0.5
    if cand_exp is None:
        return 0.2
    return max(0.0, min(1.0, cand_exp / req_exp))


def _region_part(requirements: dict[str, Any], resume: dict[str, Any]) -> float:
    req_region = _norm_text(requirements.get("region"))
    area = _norm_text(resume.get("area"))
    if not req_region or req_region in {"любой", "any"}:
        return 0.5
    if req_region in area or area in req_region:
        return 1.0
    req_tokens = set(_tokenize(req_region))
    area_tokens = set(_tokenize(area))
    overlap = len(req_tokens & area_tokens)
    return (overlap / len(req_tokens)) if req_tokens else 0.0


def _fallback_score_for_resume(requirements: dict[str, Any], resume: dict[str, Any]) -> int:
    min_score = int(settings.llm_prescore_fallback_min_score or 0)
    max_score = int(settings.llm_prescore_fallback_max_score or 100)
    if min_score > max_score:
        min_score, max_score = max_score, min_score
    w_skills = max(0.7, float(settings.llm_prescore_fallback_weight_skills or 0.4))
    w_pos = max(0.0, float(settings.llm_prescore_fallback_weight_position or 0.25))
    w_exp = max(0.0, float(settings.llm_prescore_fallback_weight_experience or 0.2))
    w_region = max(0.0, float(settings.llm_prescore_fallback_weight_region or 0.15))
    total_w = w_skills + w_pos + w_exp + w_region
    if total_w <= 0:
        return max(min_score, min(100, max_score))
    skills_part = _skills_part(requirements, resume)
    position_part = _position_part(requirements, resume)
    experience_part = _experience_part(requirements, resume)
    region_part = _region_part(requirements, resume)

    weighted_part = (
        skills_part * w_skills
        + position_part * w_pos
        + experience_part * w_exp
        + region_part * w_region
    ) / total_w
    raw = int(round(min_score + (max_score - min_score) * weighted_part))

    soft_signals = [
        _norm_text(s)
        for s in (requirements.get("soft_signals") or [])
        if _norm_text(s)
    ]
    if soft_signals:
        blob = " ".join(
            [
                _norm_text(resume.get("title")),
                " ".join(_norm_text(x) for x in (resume.get("skills") or []) if _norm_text(x)),
                _norm_text(resume.get("about")),
                _norm_text(resume.get("raw_text")),
            ]
        )
        hits = sum(1 for s in soft_signals if s in blob)
        if hits > 0:
            raw += min(10, hits * 3)
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
            "status": "done",
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
            "unresolved_count": 0,
            "recovery_batches_total": 0,
            "single_resume_attempts_total": 0,
            "single_resume_fail_count": 0,
            "llm_only_complete": True,
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
    unresolved_ids: set[str] = set()
    single_attempt_by_id: dict[str, int] = {}
    single_resume_attempts_total = 0
    single_resume_fail_count = 0
    recovery_batches_total = 0

    cfg = llm_client.get_llm_config(db)
    llm_enabled = bool((cfg.endpoint or "").strip())

    model = (cfg.fast_model or cfg.model or "qwen2.5:7b").strip()
    base_batch_size = max(1, min(50, int(cfg.llm_fast_batch_size or 5)))
    recovery_enabled = bool(getattr(settings, "llm_prescore_recovery_enabled", True))
    single_retry_max_attempts = max(
        1,
        int(getattr(settings, "llm_prescore_single_retry_max_attempts", 3) or 3),
    )
    recovery_max_depth = max(
        1,
        int(getattr(settings, "llm_prescore_recovery_max_depth", 10) or 10),
    )
    budget_seconds = float(max_seconds) if max_seconds is not None else None
    header = _format_prescore_header(requirements)
    fallback_enabled = bool(settings.llm_prescore_enable_fallback)

    pending: list[tuple[list[dict[str, Any]], int, int]] = [(list(resumes), base_batch_size, 0)]
    batch_seq = 0
    while pending:
        rows, task_batch_size, depth = pending.pop(0)
        chunk_start = 0
        while chunk_start < len(rows):
            chunk = rows[chunk_start : chunk_start + max(1, task_batch_size)]
            chunk_start += len(chunk)
            if not chunk:
                continue
            if budget_seconds is not None and (time.monotonic() - t0) >= budget_seconds:
                budget_exhausted = True
                for row in chunk + rows[chunk_start:]:
                    rid = rid_of(row)
                    if rid and rid not in out:
                        unresolved_ids.add(rid)
                        fallback_reason_by_id[rid] = "limit-exhausted"
                for left_rows, _left_size, _left_depth in pending:
                    for row in left_rows:
                        rid = rid_of(row)
                        if rid and rid not in out:
                            unresolved_ids.add(rid)
                            fallback_reason_by_id[rid] = "limit-exhausted"
                pending.clear()
                break
            if not llm_enabled:
                for row in chunk:
                    rid = rid_of(row)
                    if rid and rid not in out:
                        unresolved_ids.add(rid)
                        fallback_reason_by_id[rid] = "limit-exhausted"
                continue

            batch_seq += 1
            batch_started = time.monotonic()
            resumes_block = "\n".join(_format_resume_for_prescore_batch(r) for r in chunk)
            prompt = PRESCORE_BATCH_PROMPT.format(**header, resumes_block=resumes_block)
            prompt_chars_total += len(prompt)
            prompt_count += 1
            arr, retry_count, fail_reason = _fetch_prescore_array(
                prompt,
                model,
                batch_label=f"batch#{batch_seq} depth={depth} size={len(chunk)}",
                db=db,
            )
            llm_calls_total += 1 + retry_count
            if depth > 0:
                llm_calls_refill += 1 + retry_count
            if len(chunk) == 1:
                single_resume_attempts_total += 1 + retry_count
            if not arr:
                parse_fail_count += 1
                chunk_scores = {}
            else:
                chunk_scores = _scores_from_array_for_chunk(arr, chunk, rid_of)
            out.update(chunk_scores)
            missing_rows: list[dict[str, Any]] = []
            for row in chunk:
                rid = rid_of(row)
                if rid and rid not in chunk_scores and rid not in out:
                    missing_rows.append(row)

            if missing_rows:
                if len(chunk) == 1:
                    row = missing_rows[0]
                    rid = rid_of(row)
                    if rid:
                        attempt_no = int(single_attempt_by_id.get(rid, 0)) + 1
                        single_attempt_by_id[rid] = attempt_no
                        can_retry_single = (
                            recovery_enabled
                            and attempt_no < single_retry_max_attempts
                            and not budget_exhausted
                        )
                        if can_retry_single:
                            pending.append(([row], 1, depth + 1))
                            recovery_batches_total += 1
                        else:
                            unresolved_ids.add(rid)
                            fallback_reason_by_id[rid] = fail_reason if fail_reason else "parse-fail"
                            single_resume_fail_count += 1
                else:
                    can_split = (
                        recovery_enabled
                        and depth < recovery_max_depth
                        and task_batch_size > 1
                    )
                    if can_split:
                        next_batch = max(1, (task_batch_size + 1) // 2)
                        pending.append((missing_rows, next_batch, depth + 1))
                        recovery_batches_total += 1
                        refill_attempted_total += len(missing_rows)
                    else:
                        for row in missing_rows:
                            rid = rid_of(row)
                            if rid and rid not in out:
                                unresolved_ids.add(rid)
                                fallback_reason_by_id[rid] = fail_reason if fail_reason else "limit-exhausted"

            missing_scores = len(missing_rows)
            if depth > 0:
                refill_gain_total += len(chunk_scores)
            logger.info(
                "pre-screening batch: phase=%s depth=%s batch_size=%s missing_scores=%s retry_count=%s elapsed_ms=%s",
                phase,
                depth,
                len(chunk),
                missing_scores,
                retry_count,
                int((time.monotonic() - batch_started) * 1000),
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "prescore",
                        "event": "batch_done" if depth == 0 else "recovery_done",
                        "batch_index": batch_seq,
                        "batch_size": len(chunk),
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
        if budget_exhausted:
            break

    llm_scored_count = len(out)
    fallback_scored_count = 0
    fallback_reasons = {"parse-fail": 0, "timeout": 0, "limit-exhausted": 0}
    if fallback_enabled:
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
    unresolved_count = max(
        0,
        sum(1 for r in resumes if (rid := rid_of(r)) and rid not in out),
    )
    if fallback_enabled:
        unresolved_count = 0
    coverage_ratio = float(len(out) / len(resumes)) if resumes else 1.0
    llm_only_complete = unresolved_count == 0
    status = "done"
    if not llm_only_complete:
        status = "error" if not llm_enabled else "partial"
    return out, {
        "status": status,
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
        "unresolved_count": int(unresolved_count),
        "recovery_batches_total": int(recovery_batches_total),
        "single_resume_attempts_total": int(single_resume_attempts_total),
        "single_resume_fail_count": int(single_resume_fail_count),
        "llm_only_complete": bool(llm_only_complete),
    }
