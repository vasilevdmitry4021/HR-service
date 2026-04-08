"""Оценка соответствия резюме запросу через LLM (OpenAI / Ollama-совместимый API)."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.services import llm_client

RESUME_ANALYSIS_PROMPT = """Ты — опытный HR-ассистент. Оцени соответствие резюме требованиям вакансии.

ВАЖНЫЕ ПРАВИЛА СОПОСТАВЛЕНИЯ:
1. Термины на разных языках считаются эквивалентными:
   - "микросервисы" = "microservices" = "микросервисная архитектура" = "MSA"
   - "системный аналитик" = "system analyst" = "systems analyst"
   - "Python" = "питон", "JavaScript" = "JS"
2. Учитывай родственные навыки и технологии:
   - Docker, Kubernetes, API Gateway -> опыт с микросервисами
   - REST API, gRPC, Kafka, RabbitMQ -> работа с распределенными системами
   - SQL, PostgreSQL, MySQL -> работа с базами данных
3. Не требуй точного совпадения формулировок — оценивай смысловое сходство
4. Анализируй контекст опыта работы, а не только явно указанные навыки

ЖЁСТКОЕ ТРЕБОВАНИЕ ПО ЧИСЛОВЫМ ПАРАМЕТРАМ:
Если кандидат не соответствует числовому требованию (например, опыт 8 лет при требовании от 9, возраст вне диапазона, зарплата ниже минимальной) — это критический минус. Существенно снижай оценку и обязательно укажи несоответствие в gaps.

Требования вакансии:
- Должность: {position}
- Ключевые навыки: {skills}
- Минимальный опыт: {exp_min}
- Возраст: {age_bounds}
- Минимальная зарплата: {salary_from}
- Регион: {region}

Резюме кандидата:
- Текущая/последняя должность: {r_title}
- Указанные навыки (теги в резюме): {r_skills}
- Общий опыт работы: {r_exp} лет
- Возраст: {r_age}
- Зарплата: {r_salary}
- Регион проживания: {r_area}

Текст «О себе» и дополнительные сведения с сайта резюме (если есть — опирайся на них в первую очередь):
{r_about}

Образование:
{r_education}

Сводка по местам работ (описания позиций):
{r_work_summary}

КРИТЕРИИ ОЦЕНКИ:
- 80-100: Полное соответствие (все ключевые навыки + достаточный опыт)
- 60-79: Хорошее соответствие (большинство навыков, возможно меньше опыта)
- 40-59: Частичное соответствие (часть навыков, есть потенциал роста)
- 20-39: Слабое соответствие (мало пересечений, но есть релевантный опыт)
- 0-19: Не соответствует (другая специализация)

Верни ТОЛЬКО JSON:
{{
    "llm_score": <число 0-100>,
    "is_relevant": <true если кандидат перспективен для рассмотрения>,
    "strengths": ["сильная сторона 1", "сильная сторона 2"],
    "gaps": ["чего не хватает 1"],
    "summary": "Краткий вывод в 1-2 предложения с обоснованием оценки"
}}

Пример вывода:
{{
    "llm_score": 72,
    "is_relevant": true,
    "strengths": ["Опыт работы с микросервисами", "Знание PostgreSQL"],
    "gaps": ["Нет опыта с Kubernetes"],
    "summary": "Кандидат имеет хорошую базу в backend-разработке, недостаёт опыта оркестрации."
}}"""

RESUME_BATCH_PROMPT = """Ты — опытный HR-ассистент. Оцени соответствие КАЖДОГО из перечисленных резюме требованиям вакансии.

ВАЖНЫЕ ПРАВИЛА СОПОСТАВЛЕНИЯ:
1. Термины на разных языках считаются эквивалентными:
   - "микросервисы" = "microservices" = "микросервисная архитектура" = "MSA"
   - "системный аналитик" = "system analyst" = "systems analyst"
   - "Python" = "питон", "JavaScript" = "JS"
2. Учитывай родственные навыки и технологии:
   - Docker, Kubernetes, API Gateway -> опыт с микросервисами
   - REST API, gRPC, Kafka, RabbitMQ -> работа с распределенными системами
   - SQL, PostgreSQL, MySQL -> работа с базами данных
3. Не требуй точного совпадения формулировок — оценивай смысловое сходство
4. ВАЖНО: Анализируй ВСЕ данные резюме, включая описания опыта работы и раздел "о себе" — навыки часто указаны там, а не только в тегах
5. Числовые несоответствия (опыт, возраст, зарплата) — критический минус, снижай оценку и укажи в gaps

Требования вакансии:
- Должность: {position}
- Ключевые навыки: {skills}
- Минимальный опыт: {exp_min}
- Возраст: {age_bounds}
- Минимальная зарплата: {salary_from}
- Регион: {region}

Резюме для оценки (каждое помечено resume_id):
{resumes_block}

Верни ТОЛЬКО JSON-массив с объектами в том же порядке. Каждый объект:
{{"resume_id": "<строго из списка>", "llm_score": 0-100, "is_relevant": true/false, "strengths": [], "gaps": [], "summary": "..."}}"""


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
    lst = skills or []
    if len(lst) <= max_items:
        return ", ".join(lst)
    return ", ".join(lst[:max_items]) + " ..."


def _shorten_text(text: str, max_chars: int) -> str:
    t = text.strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1] + "…"


def _resume_about_for_prompt(resume: dict[str, Any], max_chars: int = 14_000) -> str:
    raw = resume.get("about")
    if not isinstance(raw, str) or not raw.strip():
        return "не указано"
    return _shorten_text(raw, max_chars)


def _resume_education_for_prompt(resume: dict[str, Any], max_chars: int = 2_000) -> str:
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


def _resume_work_summary_for_prompt(resume: dict[str, Any], max_chars: int = 8_000) -> str:
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
        skills = _truncate_skills(resume.get("skills") or [])
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
        frag = _shorten_text(about, 1000).replace("\n", " ")
        base += f" | о себе: {frag}"
    work_summary = _resume_work_summary_for_prompt(resume, max_chars=2500)
    if work_summary and work_summary != "не указано":
        work_frag = work_summary.replace("\n", " | ")
        base += f" | описание опыта работы: {work_frag}"
    return base


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
    user_prompt: str, db: Session | None = None
) -> dict[str, Any] | None:
    if not llm_client.llm_connection_configured(db):
        return None
    raw = llm_client.call_llm_for_json_object(db, user_prompt, timeout=60.0)
    return raw


def _call_llm_raw(
    user_prompt: str, timeout: float = 90.0, db: Session | None = None
) -> str | None:
    """Вызов LLM, возвращает сырой текст ответа (для batch)."""
    if not llm_client.llm_connection_configured(db):
        return None
    cfg = llm_client.get_llm_config(db)
    return llm_client.call_llm_user_prompt(
        db,
        user_prompt,
        model=cfg.model,
        format_json=True,
        timeout=timeout,
    )


def analyze_resumes_batch(
    requirements: dict[str, Any],
    resumes: list[dict[str, Any]],
    batch_size: int = 1,
    db: Session | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Анализирует несколько резюме через LLM. При batch_size>1 — одним запросом на группу.
    При сбое парсинга batch — fallback на одиночные analyze_resume.
    Возвращает dict[resume_id, analysis].
    """
    if not resumes:
        return {}

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
    batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(resumes), batch_size):
        batches.append(resumes[i : i + batch_size])

    for batch in batches:
        if batch_size > 1 and len(batch) > 1:
            resumes_block = "\n".join(_format_resume_for_batch(r) for r in batch)
            prompt = RESUME_BATCH_PROMPT.format(
                **header,
                resumes_block=resumes_block,
            )
            raw = _call_llm_raw(prompt, db=db)
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
                for r in batch:
                    rid = str(r.get("id", r.get("hh_resume_id", "")))
                    result[rid] = analyze_resume(requirements, r, db=db)
        else:
            for r in batch:
                rid = str(r.get("id", r.get("hh_resume_id", "")))
                result[rid] = analyze_resume(requirements, r, db=db)

    return result


def analyze_resume(
    requirements: dict[str, Any],
    resume: dict[str, Any],
    db: Session | None = None,
) -> dict[str, Any]:
    """Возвращает поля для LLMAnalysisOut; при ошибке или без endpoint — пустой анализ."""
    exp_str, age_str, sal_str = _format_numeric_bounds(requirements)
    r_age, r_salary = _format_resume_numeric(resume)
    skill_tags = resume.get("skills") or []
    if isinstance(skill_tags, str):
        skill_tags = [skill_tags]
    user_prompt = RESUME_ANALYSIS_PROMPT.format(
        skills=", ".join(requirements.get("skills") or []) or "не указаны",
        exp_min=exp_str,
        age_bounds=age_str,
        salary_from=sal_str,
        region=requirements.get("region") or "любой",
        position=", ".join(requirements.get("position_keywords") or []) or "не указана",
        r_title=resume.get("title", ""),
        r_skills=", ".join(skill_tags) if skill_tags else "не указаны",
        r_exp=resume.get("experience_years", 0),
        r_age=r_age,
        r_salary=r_salary,
        r_area=resume.get("area", ""),
        r_about=_resume_about_for_prompt(resume),
        r_education=_resume_education_for_prompt(resume),
        r_work_summary=_resume_work_summary_for_prompt(resume),
    )

    raw = _call_llm_for_json(user_prompt, db=db)
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
