"""Быстрая числовая оценка резюме лёгкой моделью (pre-screening перед детальным анализом)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.services import llm_client
from app.services.llm_resume_analyzer import _format_resume_for_batch

logger = logging.getLogger(__name__)

PRESCORE_BATCH_PROMPT = """Ты — HR-скринер. По каждому резюме дай одну оценку соответствия требованиям (0–100).
Учитывай навыки, должность, опыт; синонимы и разные языки эквивалентны (Python = питон).

Требования:
- Должность: {position}
- Ключевые навыки: {skills}
- Минимальный опыт: {exp_min}
- Регион: {region}

Резюме (без списка тегов навыков — ориентируйся на должность, опыт, «о себе», описание работы):
{resumes_block}

Верни ТОЛЬКО JSON-массив объектов в том же порядке, что резюме в списке:
[{{"resume_id": "<id из списка>", "score": <целое 0-100>}}, ...]"""


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
    for item in arr:
        if not isinstance(item, dict):
            continue
        rid = _resume_id_from_item(item)
        sc = _parse_score(item)
        if rid and sc is not None:
            by_id[rid] = sc

    n = min(len(arr), len(chunk))
    for i in range(n):
        k = rid_of(chunk[i])
        if not k:
            continue
        it = arr[i]
        if not isinstance(it, dict):
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
) -> list[dict[str, Any]] | None:
    raw = _call_llm_raw_with_model(
        prompt,
        model,
        timeout=240.0,
        use_json_constraint=True,
        db=db,
    )
    arr = _parse_prescore_llm_text(raw)
    raw_loose: str | None = None
    if not arr:
        raw_loose = _call_llm_raw_with_model(
            prompt,
            model,
            timeout=240.0,
            use_json_constraint=False,
            db=db,
        )
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
    return arr


def prescore_resumes_batch(
    requirements: dict[str, Any],
    resumes: list[dict[str, Any]],
    db: Session | None = None,
) -> dict[str, int]:
    """
    Возвращает словарь resume_id -> оценка 0–100 только из ответа LLM.
    Без endpoint, при ошибке или пустом ответе — пустой словарь (или только то, что удалось разобрать).
    """
    if not resumes:
        return {}

    def rid_of(r: dict[str, Any]) -> str:
        return str(r.get("id", r.get("hh_resume_id", "")))

    out: dict[str, int] = {}

    cfg = llm_client.get_llm_config(db)
    if not (cfg.endpoint or "").strip():
        return out

    model = (cfg.fast_model or cfg.model or "qwen2.5:7b").strip()
    batch_size = max(1, min(50, int(cfg.llm_fast_batch_size or 5)))
    header = _format_prescore_header(requirements)

    for start in range(0, len(resumes), batch_size):
        chunk = resumes[start : start + batch_size]
        resumes_block = "\n".join(
            _format_resume_for_batch(r, include_skill_tags=False) for r in chunk
        )
        prompt = PRESCORE_BATCH_PROMPT.format(
            **header,
            resumes_block=resumes_block,
        )
        arr = _fetch_prescore_array(
            prompt,
            model,
            batch_label=f"батч {start}..{start + len(chunk) - 1}",
            db=db,
        )
        if not arr:
            continue
        chunk_scores = _scores_from_array_for_chunk(arr, chunk, rid_of)
        out.update(chunk_scores)

    if settings.llm_prescore_refill_enabled:
        max_refill = max(0, int(settings.llm_prescore_refill_max_llm_calls or 0))
        failed: set[str] = set()
        refill_calls = 0
        while refill_calls < max_refill:
            missing = [
                r
                for r in resumes
                if rid_of(r) and rid_of(r) not in out and rid_of(r) not in failed
            ]
            if not missing:
                break
            one = missing[:1]
            resumes_block = "\n".join(
                _format_resume_for_batch(r, include_skill_tags=False) for r in one
            )
            prompt = PRESCORE_BATCH_PROMPT.format(
                **header,
                resumes_block=resumes_block,
            )
            arr = _fetch_prescore_array(
                prompt,
                model,
                batch_label=f"дозапрос resume {rid_of(one[0])}",
                db=db,
            )
            refill_calls += 1
            rid0 = rid_of(one[0])
            if not arr:
                failed.add(rid0)
                continue
            chunk_scores = _scores_from_array_for_chunk(arr, one, rid_of)
            if rid0 in chunk_scores:
                out.update(chunk_scores)
            else:
                failed.add(rid0)

        still = sum(
            1 for r in resumes if rid_of(r) and rid_of(r) not in out
        )
        if still:
            logger.warning(
                "pre-screening: без числовой оценки осталось резюме: %s (из %s)",
                still,
                len(resumes),
            )

    return out
