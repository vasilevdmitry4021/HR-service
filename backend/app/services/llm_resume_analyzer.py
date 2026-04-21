"""Оценка соответствия резюме запросу через LLM (OpenAI / Ollama-совместимый API)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.services import llm_client

RESUME_ANALYSIS_PROMPT = """Оцени соответствие резюме вакансии по смыслу (синонимы, близкие роли и смежные технологии считаются релевантными).
Числовые ограничения (опыт, возраст, зарплата, регион) учитывай как корректирующий фактор, не как автоматический отказ.
В gaps указывай только 1-3 наиболее критичных пробела.

Вакансия:
- должность: {position}
- навыки: {skills}
- опыт: {exp_min}
- возраст: {age_bounds}
- зарплата от: {salary_from}
- регион: {region}

Резюме:
- должность: {r_title}
- навыки (теги): {r_skills}
- опыт: {r_exp}
- возраст: {r_age}
- зарплата: {r_salary}
- регион: {r_area}
- о себе: {r_about}
- образование: {r_education}
- опыт работы: {r_work_summary}

Верни строго JSON-объект:
{{
  "llm_score": 0-100,
  "is_relevant": true/false,
  "strengths": ["..."],
  "gaps": ["..."],
  "summary": "1-2 предложения"
}}"""

RESUME_BATCH_PROMPT = """Оцени соответствие каждого резюме вакансии по смыслу.
Синонимы/близкие роли учитывай как релевантные, числовые ограничения используй как корректирующий фактор.
В gaps указывай только 1-3 ключевых пробела.

Вакансия:
- должность: {position}
- навыки: {skills}
- опыт: {exp_min}
- возраст: {age_bounds}
- зарплата от: {salary_from}
- регион: {region}

Резюме:
{resumes_block}

Верни строго JSON-массив объектов в исходном порядке:
{{"resume_id":"...","llm_score":0-100,"is_relevant":true/false,"strengths":[],"gaps":[],"summary":"..."}}"""


def _format_numeric_bounds(requirements: dict[str, Any]) -> tuple[str, str, str]:
    """Возвращает (exp_min, age_bounds, salary_from) для промпта."""
    exp = requirements.get("experience_years_min")
    exp_str = f"от {exp} лет" if exp is not None else "не указан"

    age_min = requirements.get("age_min")
    age_max = requirements.get("age_max")
    if age_min is not None and age_max is not None:
        age_str = f"от {age_min} до {age_max} лет"
    elif age_min is not None:
        age_str = f"от {age_min} лет"
    elif age_max is not None:
        age_str = f"до {age_max} лет"
    else:
        age_str = "не указан"

    sal = requirements.get("salary_from")
    sal_str = f"{sal}" if sal is not None else "не указано"

    return exp_str, age_str, sal_str


def _format_resume_numeric(resume: dict[str, Any]) -> tuple[str, str]:
    """Возвращает (r_age, r_salary) для промпта."""
    age = resume.get("age")
    r_age = str(age) if age is not None else "не указан"
    sal = resume.get("salary")
    if isinstance(sal, dict) and sal.get("amount") is not None:
        cur = sal.get("currency", "")
        r_salary = f"{sal['amount']} {cur}".strip()
    else:
        r_salary = "не указана"
    return r_age, r_salary


def _truncate_skills(skills: list[str], max_items: int = 12) -> str:
    max_items = max(1, int(max_items or 1))
    lst = skills or []
    if len(lst) <= max_items:
        return ", ".join(lst)
    return ", ".join(lst[:max_items]) + " ..."


def _shorten_text(text: str, max_chars: int) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1] + "…"


def _clean_inline_text(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def _top_resume_fragments(
    resume: dict[str, Any],
    *,
    max_items: int = 8,
    max_item_chars: int = 140,
) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    work_items = resume.get("work_experience") or []
    for it in work_items:
        if not isinstance(it, dict):
            continue
        position = _clean_inline_text(it.get("position"))
        company = _clean_inline_text(it.get("company"))
        description = _clean_inline_text(it.get("description"))
        head = " - ".join(x for x in (position, company) if x)
        if head:
            key = head.lower()
            if key not in seen:
                seen.add(key)
                items.append(_shorten_text(head, max_item_chars))
        for piece in re.split(r"[.;\n]", description):
            text = _clean_inline_text(piece)
            if len(text) < 25:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(_shorten_text(text, max_item_chars))
            if len(items) >= max_items:
                return items

    for source in (
        _clean_inline_text(resume.get("about")),
        _clean_inline_text(resume.get("raw_text")),
    ):
        for piece in re.split(r"[.;\n]", source):
            text = _clean_inline_text(piece)
            if len(text) < 30:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(_shorten_text(text, max_item_chars))
            if len(items) >= max_items:
                return items
    return items


def build_prescore_semantic_summary(
    resume: dict[str, Any],
    *,
    max_chars: int = 1700,
    highlights_limit: int = 8,
    recent_jobs_limit: int = 3,
) -> str:
    """Короткая semantic summary для pre-score без explainability-полей."""
    title = _shorten_text(_clean_inline_text(resume.get("title")), 80)
    skills = _truncate_skills(resume.get("skills") or [], max_items=10)
    exp = resume.get("experience_years", 0)
    area = _shorten_text(_clean_inline_text(resume.get("area")), 80)
    about = _resume_about_for_prompt(resume, max_chars=420)
    parts = [
        f"должность: {title or 'не указана'}",
        f"навыки: {skills or 'не указаны'}",
        f"опыт: {exp} лет",
        f"регион: {area or 'не указан'}",
    ]
    if about != "не указано":
        parts.append(f"о себе: {_clean_inline_text(about)}")

    jobs: list[str] = []
    work_items = resume.get("work_experience") or []
    for it in work_items[: max(0, recent_jobs_limit)]:
        if not isinstance(it, dict):
            continue
        position = _clean_inline_text(it.get("position"))
        company = _clean_inline_text(it.get("company"))
        description = _clean_inline_text(it.get("description"))
        head = " - ".join(x for x in (position, company) if x)
        if description:
            jobs.append(_shorten_text(f"{head}: {description}" if head else description, 220))
        elif head:
            jobs.append(_shorten_text(head, 220))
    if jobs:
        parts.append("последние места работы: " + " || ".join(jobs))

    highlights = _top_resume_fragments(
        resume,
        max_items=max(1, highlights_limit),
        max_item_chars=150,
    )
    if highlights:
        parts.append("ключевые фрагменты: " + " | ".join(highlights))

    return _shorten_text(" | ".join(parts), max_chars)


def _resume_about_for_prompt(resume: dict[str, Any], max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = int(settings.llm_detailed_about_max_chars or 2400)
    raw = resume.get("about")
    if not isinstance(raw, str) or not raw.strip():
        return "не указано"
    return _shorten_text(raw, max_chars)


def _resume_education_for_prompt(resume: dict[str, Any], max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = int(settings.llm_detailed_education_max_chars or 1000)
    items = resume.get("education") or []
    lines: list[str] = []
    for e in items:
        if isinstance(e, dict):
            s = str(e.get("summary") or "").strip()
            if s:
                lines.append(s)
    if not lines:
        return "не указано"
    return _shorten_text("\n".join(lines), max_chars)


def _resume_work_summary_for_prompt(resume: dict[str, Any], max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = int(settings.llm_detailed_work_summary_max_chars or 3000)
    items = resume.get("work_experience") or []
    parts: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        pos = str(it.get("position") or "").strip()
        comp = str(it.get("company") or "").strip()
        desc = str(it.get("description") or "").strip()
        head = f"{pos} ({comp})".strip().strip("()")
        if desc:
            line = f"{head}: {desc}" if head else desc
        else:
            line = head
        if line:
            parts.append(line)
    if not parts:
        return "не указано"
    return _shorten_text("\n".join(parts), max_chars)


def _format_resume_for_batch(
    resume: dict[str, Any],
    *,
    include_skill_tags: bool = True,
) -> str:
    rid = str(resume.get("id", resume.get("hh_resume_id", "")))
    title = (resume.get("title") or "")[:80]
    exp = resume.get("experience_years", 0)
    age = resume.get("age", "не указан")
    sal = resume.get("salary")
    if isinstance(sal, dict) and sal.get("amount") is not None:
        salary_str = f"{sal['amount']} {sal.get('currency', '')}".strip()
    else:
        salary_str = "не указана"
    area = resume.get("area", "")
    if include_skill_tags:
        skills = _truncate_skills(
            resume.get("skills") or [],
            max_items=int(settings.llm_detailed_skills_max_items or 12),
        )
        base = (
            f"[resume_id={rid}] {title} | навыки (теги): {skills} | опыт: {exp} лет | "
            f"возраст: {age} | зарплата: {salary_str} | регион: {area}"
        )
    else:
        base = (
            f"[resume_id={rid}] {title} | опыт: {exp} лет | "
            f"возраст: {age} | зарплата: {salary_str} | регион: {area}"
        )
    about = resume.get("about")
    if isinstance(about, str) and about.strip():
        frag = _shorten_text(
            about,
            int(settings.llm_detailed_about_max_chars or 2400),
        ).replace("\n", " ")
        base += f" | о себе: {frag}"
    work_summary = _resume_work_summary_for_prompt(resume, max_chars=None)
    if work_summary and work_summary != "не указано":
        work_frag = work_summary.replace("\n", " | ")
        base += f" | описание опыта работы: {work_frag}"
    return base


def _format_resume_for_prescore_batch(resume: dict[str, Any]) -> str:
    """Компактный формат для pre-score: только ключевые признаки и короткие фрагменты."""
    rid = str(resume.get("id", resume.get("hh_resume_id", "")))
    provided_summary = _clean_inline_text(resume.get("semantic_summary"))
    if provided_summary:
        summary = _shorten_text(provided_summary, 1700)
    else:
        summary = build_prescore_semantic_summary(
            resume,
            max_chars=1700,
            highlights_limit=8,
            recent_jobs_limit=3,
        )
    return f"[resume_id={rid}] {summary}"


def _format_resume_for_rerank_document(resume: dict[str, Any]) -> str:
    """Стабильный короткий документ для rerank (без prompt-инструкций)."""
    title = _shorten_text(_clean_inline_text(resume.get("title")), 100) or "не указана"
    skills = _truncate_skills([str(x) for x in (resume.get("skills") or [])], max_items=12) or "не указаны"
    exp = resume.get("experience_years")
    exp_str = f"{exp}" if isinstance(exp, (int, float)) else "не указан"
    area = _shorten_text(_clean_inline_text(resume.get("area")), 100) or "не указан"
    summary = _clean_inline_text(resume.get("semantic_summary")) or build_prescore_semantic_summary(
        resume,
        max_chars=1200,
        highlights_limit=6,
        recent_jobs_limit=3,
    )
    highlights = _top_resume_fragments(
        resume,
        max_items=3,
        max_item_chars=180,
    )
    parts = [
        f"должность: {title}",
        f"навыки: {skills}",
        f"опыт: {exp_str}",
        f"регион: {area}",
        f"summary: {_shorten_text(summary, 1200)}",
    ]
    if highlights:
        parts.append("опыт_фрагменты: " + " | ".join(highlights))
    return _shorten_text(" || ".join(parts), 2000)


def _format_resume_for_analyze_batch(resume: dict[str, Any]) -> str:
    """Расширенный формат для batch analyze (с тегами и более длинным контекстом)."""
    return _format_resume_for_batch(resume, include_skill_tags=True)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_json_array(text: str) -> list[dict[str, Any]] | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
        return None
    except json.JSONDecodeError:
        return None


def _call_llm_for_json(
    user_prompt: str,
    db: Session | None = None,
    *,
    runtime_config: llm_client.LLMRuntimeConfig | None = None,
    timeout: float | None = None,
) -> dict[str, Any] | None:
    cfg = runtime_config or llm_client.get_llm_config(db)
    if not llm_client.llm_connection_configured_runtime(cfg):
        return None
    raw = llm_client.call_llm_for_json_object(
        db,
        user_prompt,
        timeout=float(timeout or settings.llm_detailed_single_timeout_seconds or 90.0),
        runtime_config=cfg,
    )
    return raw


def _call_llm_raw(
    user_prompt: str,
    timeout: float = 90.0,
    db: Session | None = None,
    *,
    runtime_config: llm_client.LLMRuntimeConfig | None = None,
) -> str | None:
    """Вызов LLM, возвращает сырой текст ответа (для batch)."""
    cfg = runtime_config or llm_client.get_llm_config(db)
    if not llm_client.llm_connection_configured_runtime(cfg):
        return None
    return llm_client.call_llm_user_prompt(
        db,
        user_prompt,
        model=cfg.model,
        format_json=True,
        timeout=timeout,
        runtime_config=cfg,
    )


def analyze_resumes_batch(
    requirements: dict[str, Any],
    resumes: list[dict[str, Any]],
    batch_size: int = 1,
    db: Session | None = None,
    *,
    runtime_config: llm_client.LLMRuntimeConfig | None = None,
    include_metrics: bool = False,
) -> dict[str, dict[str, Any]] | tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """
    Анализирует несколько резюме через LLM. При batch_size>1 — одним запросом на группу.
    При сбое парсинга batch — fallback на одиночные analyze_resume.
    Возвращает dict[resume_id, analysis].
    """
    if not resumes:
        empty_metrics = {
            "detailed_batch_count": 0,
            "detailed_batch_parse_fail_count": 0,
            "detailed_fallback_single_resume_count": 0,
            "detailed_prompt_chars_avg": 0,
            "detailed_prompt_chars_max": 0,
        }
        return ({}, empty_metrics) if include_metrics else {}

    exp_str, age_str, sal_str = _format_numeric_bounds(requirements)
    header = {
        "position": ", ".join(requirements.get("position_keywords") or []) or "не указана",
        "skills": ", ".join(requirements.get("skills") or []) or "не указаны",
        "exp_min": exp_str,
        "age_bounds": age_str,
        "salary_from": sal_str,
        "region": requirements.get("region") or "любой",
    }

    result: dict[str, dict[str, Any]] = {}
    metrics = {
        "detailed_batch_count": 0,
        "detailed_batch_parse_fail_count": 0,
        "detailed_fallback_single_resume_count": 0,
        "detailed_prompt_chars_avg": 0,
        "detailed_prompt_chars_max": 0,
    }
    prompt_sizes: list[int] = []
    batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(resumes), batch_size):
        batches.append(resumes[i : i + batch_size])

    for batch in batches:
        if batch_size > 1 and len(batch) > 1:
            metrics["detailed_batch_count"] += 1
            resumes_block = "\n".join(_format_resume_for_analyze_batch(r) for r in batch)
            prompt = RESUME_BATCH_PROMPT.format(
                **header,
                resumes_block=resumes_block,
            )
            prompt_sizes.append(len(prompt))
            raw = _call_llm_raw(
                prompt,
                timeout=float(settings.llm_detailed_batch_timeout_seconds or 90.0),
                db=db,
                runtime_config=runtime_config,
            )
            arr = _extract_json_array(raw) if raw else None
            if arr and len(arr) >= len(batch):
                by_id = {str(x.get("resume_id", "")): x for x in arr if x.get("resume_id")}
                for r in batch:
                    rid = str(r.get("id", r.get("hh_resume_id", "")))
                    item = by_id.get(rid)
                    if item:
                        result[rid] = _normalize_analysis(item)
                    else:
                        result[rid] = _empty_analysis()
            else:
                metrics["detailed_batch_parse_fail_count"] += 1
                for r in batch:
                    rid = str(r.get("id", r.get("hh_resume_id", "")))
                    metrics["detailed_fallback_single_resume_count"] += 1
                    result[rid] = analyze_resume(
                        requirements,
                        r,
                        db=db,
                        runtime_config=runtime_config,
                    )
        else:
            for r in batch:
                rid = str(r.get("id", r.get("hh_resume_id", "")))
                result[rid] = analyze_resume(
                    requirements,
                    r,
                    db=db,
                    runtime_config=runtime_config,
                )

    if prompt_sizes:
        metrics["detailed_prompt_chars_avg"] = int(sum(prompt_sizes) / len(prompt_sizes))
        metrics["detailed_prompt_chars_max"] = max(prompt_sizes)
    return (result, metrics) if include_metrics else result


def analyze_resume(
    requirements: dict[str, Any],
    resume: dict[str, Any],
    db: Session | None = None,
    *,
    runtime_config: llm_client.LLMRuntimeConfig | None = None,
) -> dict[str, Any]:
    """Возвращает поля для LLMAnalysisOut; при ошибке или без endpoint — пустой анализ."""
    exp_str, age_str, sal_str = _format_numeric_bounds(requirements)
    r_age, r_salary = _format_resume_numeric(resume)
    skill_tags = resume.get("skills") or []
    if isinstance(skill_tags, str):
        skill_tags = [skill_tags]
    req_skills = _truncate_skills(
        [str(x) for x in (requirements.get("skills") or []) if str(x).strip()],
        max_items=int(settings.llm_detailed_skills_max_items or 12),
    )
    resume_skills = _truncate_skills(
        [str(x) for x in skill_tags if str(x).strip()],
        max_items=int(settings.llm_detailed_skills_max_items or 12),
    )
    user_prompt = RESUME_ANALYSIS_PROMPT.format(
        skills=req_skills or "не указаны",
        exp_min=exp_str,
        age_bounds=age_str,
        salary_from=sal_str,
        region=requirements.get("region") or "любой",
        position=", ".join(requirements.get("position_keywords") or []) or "не указана",
        r_title=resume.get("title", ""),
        r_skills=resume_skills or "не указаны",
        r_exp=resume.get("experience_years", 0),
        r_age=r_age,
        r_salary=r_salary,
        r_area=resume.get("area", ""),
        r_about=_resume_about_for_prompt(resume, max_chars=None),
        r_education=_resume_education_for_prompt(resume, max_chars=None),
        r_work_summary=_resume_work_summary_for_prompt(resume, max_chars=None),
    )

    raw = _call_llm_for_json(
        user_prompt,
        db=db,
        runtime_config=runtime_config,
        timeout=float(settings.llm_detailed_single_timeout_seconds or 90.0),
    )
    if not raw:
        return _empty_analysis()
    return _normalize_analysis(raw)


def _empty_analysis() -> dict[str, Any]:
    return {
        "llm_score": None,
        "is_relevant": None,
        "strengths": [],
        "gaps": [],
        "summary": None,
    }


def _str_list(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(x).strip() for x in val if x is not None and str(x).strip()]


def _normalize_analysis(raw: dict[str, Any]) -> dict[str, Any]:
    score = raw.get("llm_score")
    if not isinstance(score, (int, float)):
        score = None
    else:
        score = max(0, min(100, int(score)))

    threshold = settings.llm_relevance_threshold
    if score is not None:
        is_relevant = score >= threshold
    else:
        ir = raw.get("is_relevant")
        is_relevant = ir if isinstance(ir, bool) else None

    return {
        "llm_score": score,
        "is_relevant": is_relevant,
        "strengths": _str_list(raw.get("strengths")),
        "gaps": _str_list(raw.get("gaps")),
        "summary": raw.get("summary") if isinstance(raw.get("summary"), str) else None,
    }
