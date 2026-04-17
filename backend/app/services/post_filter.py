"""Пост-фильтрация резюме по точным границам из parsed.

Включает:
- Числовые фильтры: опыт, возраст, зарплата
- Фильтры соответствия: навыки, должность
"""

from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.services import skill_synonyms


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    return None


def _normalize_currency(val: Any) -> str | None:
    if not isinstance(val, str):
        return None
    cur = val.strip().upper()
    if not cur:
        return None
    if cur in {"RUB", "RUR"}:
        return "RUR"
    return cur


def _passes_experience(resume: dict[str, Any], exp_min: int | None) -> bool:
    if exp_min is None:
        return True
    exp = _to_int(resume.get("experience_years"))
    if exp is None:
        return False
    return exp >= exp_min


def _passes_age(resume: dict[str, Any], age_min: int | None, age_max: int | None) -> bool:
    age = _to_int(resume.get("age"))
    if age is None:
        if age_min is not None or age_max is not None:
            return False
        return True
    if age_min is not None and age < age_min:
        return False
    if age_max is not None and age > age_max:
        return False
    return True


def _passes_salary(
    resume: dict[str, Any],
    salary_from: int | None,
    salary_to: int | None,
    currency: str | None,
) -> bool:
    if salary_from is None and salary_to is None and currency is None:
        return True
    sal = resume.get("salary")
    if not isinstance(sal, dict):
        return False
    req_currency = _normalize_currency(currency)
    if req_currency is not None:
        cand_currency = _normalize_currency(sal.get("currency"))
        if cand_currency != req_currency:
            return False
    if salary_from is None and salary_to is None:
        return True
    amount = _to_int(sal.get("amount"))
    if amount is None:
        return False
    if salary_from is not None and amount < salary_from:
        return False
    if salary_to is not None and amount > salary_to:
        return False
    return True


def _passes_skills(resume: dict[str, Any], required_skills: list[str] | None) -> bool:
    """
    Проверяет, что у кандидата есть хотя бы один из требуемых навыков.
    Использует синонимы для корректного сопоставления.
    
    Если у резюме нет навыков (HH не вернул их в списке поиска), 
    кандидат пропускается — фильтрация невозможна.
    """
    if not required_skills:
        return True
    resume_skills = resume.get("skills") or []
    if not resume_skills:
        return True
    resume_skills_expanded = skill_synonyms.expand_skills_for_matching(resume_skills)
    for req_skill in required_skills:
        if not req_skill:
            continue
        req_expanded = skill_synonyms.expand_skill(req_skill)
        if req_expanded & resume_skills_expanded:
            return True
    return False


def _skills_mismatch(resume: dict[str, Any], required_skills: list[str] | None) -> bool:
    """
    Проверяет, что у кандидата ЕСТЬ навыки, но они НЕ совпадают с требуемыми.
    Возвращает True если есть явное несовпадение (кандидат должен быть отсеян).
    """
    if not required_skills:
        return False
    resume_skills = resume.get("skills") or []
    if not resume_skills:
        return False
    resume_skills_expanded = skill_synonyms.expand_skills_for_matching(resume_skills)
    for req_skill in required_skills:
        if not req_skill:
            continue
        req_expanded = skill_synonyms.expand_skill(req_skill)
        if req_expanded & resume_skills_expanded:
            return False
    return True


TECH_KEYWORDS = {
    "java": {"java", "jvm", "spring", "kotlin"},
    "python": {"python", "django", "flask", "fastapi"},
    "javascript": {"javascript", "js", "frontend", "react", "vue", "angular", "node"},
    "frontend": {"frontend", "front-end", "react", "vue", "angular", "css", "html"},
    "backend": {"backend", "back-end"},
    "php": {"php", "laravel", "symfony"},
    "go": {"go", "golang"},
    "c#": {"c#", ".net", "dotnet"},
    "ruby": {"ruby", "rails"},
    "ios": {"ios", "swift", "objective-c"},
    "android": {"android", "kotlin"},
    "devops": {"devops", "sre", "infrastructure"},
    "data": {"data", "ml", "machine learning", "analyst", "аналитик данных"},
    "qa": {"qa", "тестировщик", "tester", "quality"},
    "1c": {"1с", "1c"},
}

ANALYST_ROLE_TERMS = {
    "analyst",
    "data analyst",
    "business analyst",
    "system analyst",
    "systems analyst",
    "аналитик",
    "аналитик данных",
    "бизнес аналитик",
    "бизнес-аналитик",
    "системный аналитик",
}

ANALYST_CONFLICT_TERMS = {
    "developer",
    "engineer",
    "programmer",
    "разработчик",
    "инженер",
    "программист",
}

_WORD_SPLIT_RE = re.compile(r"[^a-zа-я0-9+#]+", re.IGNORECASE)


def _normalize_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    normalized_text = _normalize_text(text)
    normalized_term = _normalize_text(term)
    if not normalized_text or not normalized_term:
        return False
    if " " in normalized_term or "-" in normalized_term:
        return normalized_term in normalized_text
    tokens = {t for t in _WORD_SPLIT_RE.split(normalized_text) if t}
    return normalized_term in tokens


def _is_analyst_query(position_keywords: list[str] | None) -> bool:
    if not position_keywords:
        return False
    return any(
        _contains_term(str(keyword), term)
        for keyword in position_keywords
        for term in ANALYST_ROLE_TERMS
    )


def _has_role_conflict(title: str, position_keywords: list[str] | None) -> bool:
    if not title or not _is_analyst_query(position_keywords):
        return False
    title_has_analyst = any(_contains_term(title, term) for term in ANALYST_ROLE_TERMS)
    title_has_conflict = any(_contains_term(title, term) for term in ANALYST_CONFLICT_TERMS)
    return title_has_conflict and not title_has_analyst


def _title_has_different_tech(title: str, required_skills: list[str] | None) -> bool:
    """
    Проверяет, содержит ли title технологию, отличную от требуемой.
    Например, если ищем Java, а title = "Frontend-разработчик" — возвращает True.
    """
    if not required_skills or not title:
        return False
    
    title_lower = title.lower()
    req_skills_lower = {s.lower() for s in required_skills if s}
    
    req_tech_groups: set[str] = set()
    for skill in req_skills_lower:
        for group, keywords in TECH_KEYWORDS.items():
            if skill in keywords or any(kw in skill for kw in keywords):
                req_tech_groups.add(group)
    
    if not req_tech_groups:
        return False
    
    title_tech_groups: set[str] = set()
    for group, keywords in TECH_KEYWORDS.items():
        if any(kw in title_lower for kw in keywords):
            title_tech_groups.add(group)
    
    if not title_tech_groups:
        return False
    
    if title_tech_groups and not (title_tech_groups & req_tech_groups):
        return True
    
    return False


def _passes_position(
    resume: dict[str, Any],
    position_keywords: list[str] | None,
    *,
    allow_empty_title: bool,
) -> bool:
    """
    Проверяет, что название должности содержит хотя бы одно из ключевых слов.
    Использует синонимы для корректного сопоставления.
    
    Если title пустой, кандидат пропускается — фильтрация невозможна.
    """
    if not position_keywords:
        return True
    title = resume.get("title") or ""
    if not title:
        return bool(allow_empty_title)
    title_lower = title.lower()
    for kw in position_keywords:
        if not kw:
            continue
        expanded = skill_synonyms.expand_position(kw)
        if any(variant in title_lower for variant in expanded):
            return True
    return False


def _item_passes(resume: dict[str, Any], parsed: dict[str, Any]) -> bool:
    exp_min = _to_int(parsed.get("experience_years_min"))
    age_min = _to_int(parsed.get("age_min"))
    age_max = _to_int(parsed.get("age_max"))
    salary_from = _to_int(parsed.get("salary_from"))
    salary_to = _to_int(parsed.get("salary_to"))
    currency = parsed.get("currency")
    required_skills = parsed.get("skills")
    position_keywords = parsed.get("position_keywords")
    title = resume.get("title") or ""
    
    if not _passes_experience(resume, exp_min):
        return False
    if not _passes_age(resume, age_min, age_max):
        return False
    if not _passes_salary(resume, salary_from, salary_to, currency):
        return False
    
    if _skills_mismatch(resume, required_skills):
        return False
    
    if _title_has_different_tech(title, required_skills):
        return False
    if _has_role_conflict(title, position_keywords):
        return False
    
    if not _passes_skills(resume, required_skills):
        return False
    if not _passes_position(
        resume,
        position_keywords,
        allow_empty_title=bool(settings.strict_position_allow_empty_title),
    ):
        return False
    
    return True


def apply_strict_filters(
    items: list[dict[str, Any]],
    parsed: dict[str, Any],
    mode: str = "hide",
) -> list[dict[str, Any]]:
    """
    Применяет пост-фильтр по точным границам из parsed.

    Числовые фильтры:
    - experience_years >= experience_years_min
    - age_min <= age <= age_max
    - salary.amount >= salary_from

    Фильтры соответствия:
    - skills: кандидат должен иметь хотя бы один из требуемых навыков
    - position_keywords: название должности должно содержать хотя бы одно ключевое слово

    Режимы:
    - mode="hide": возвращает только прошедших фильтр.
    - mode="demote": возвращает все, добавляет strict_match=False
      не прошедшим (остальные получают strict_match=True).
    """
    skills_list = parsed.get("skills") or []
    position_list = parsed.get("position_keywords") or []
    has_any_bounds = any(
        parsed.get(k) is not None
        for k in (
            "experience_years_min",
            "age_min",
            "age_max",
            "salary_from",
            "salary_to",
            "currency",
        )
    ) or bool(skills_list) or bool(position_list)
    if not has_any_bounds:
        if mode == "demote":
            for r in items:
                r["strict_match"] = True
        return items

    if mode == "hide":
        return [r for r in items if _item_passes(r, parsed)]

    for r in items:
        r["strict_match"] = _item_passes(r, parsed)
    return items
