from __future__ import annotations

import re
from typing import Any

from app.config import settings
from app.schemas.search_filters import ResumeSearchFilters
from app.services.hh_query_planner import HHQueryPlan

_RISKY_SKILL_PATTERNS = (
    re.compile(r"\b(вайб|vibe)\w*\b", re.IGNORECASE),
    re.compile(r"\b(ai\s*pair|pair\s*programming)\b", re.IGNORECASE),
    re.compile(r"\b(copilot|cursor\s*ide|курсор\w*)\b", re.IGNORECASE),
)

# Нормализованные названия регионов из NLP → ID региона верхнего уровня HH (частые кейсы)
REGION_NAME_TO_AREA_ID: dict[str, int] = {
    "москва": 1,
    "санкт-петербург": 2,
    "екатеринбург": 3,
    "новосибирск": 4,
}

EXPERIENCE_FROM_MIN_YEARS: dict[tuple[int, int | None], str] = {
    (0, 1): "noExperience",
    (1, 3): "between1And3",
    (3, 6): "between3And6",
    (6, None): "moreThan6",
}

_DEFAULT_ROLE_TERM_MAP: dict[int, tuple[str, ...]] = {
    # HH "Аналитик" (ID 10) — консервативный fallback для role-запросов аналитиков.
    10: (
        "аналитик",
        "аналитик данных",
        "data analyst",
        "бизнес-аналитик",
        "business analyst",
        "системный аналитик",
        "system analyst",
        "systems analyst",
    )
}

_ROLE_TERM_SPLIT_RE = re.compile(r"[|,]+")


def _normalize_role_term(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_role_map(raw_map: str) -> dict[int, tuple[str, ...]]:
    parsed_map: dict[int, tuple[str, ...]] = {}
    for raw_part in str(raw_map or "").split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        role_raw, terms_raw = part.split("=", 1)
        role_id = int(role_raw.strip()) if role_raw.strip().isdigit() else None
        if role_id is None:
            continue
        terms = tuple(
            norm
            for norm in (_normalize_role_term(t) for t in _ROLE_TERM_SPLIT_RE.split(terms_raw))
            if norm
        )
        if terms:
            parsed_map[role_id] = terms
    return parsed_map


def _role_term_map() -> dict[int, tuple[str, ...]]:
    configured = _parse_role_map(settings.hh_auto_professional_role_map)
    if configured:
        return configured
    return _DEFAULT_ROLE_TERM_MAP


def infer_professional_role(parsed: dict[str, Any]) -> int | None:
    role_candidates: list[str] = []
    for field_name in ("must_position", "position_keywords"):
        terms = parsed.get(field_name)
        if isinstance(terms, list):
            for term in terms:
                if isinstance(term, str):
                    normalized = _normalize_role_term(term)
                    if normalized:
                        role_candidates.append(normalized)
    if not role_candidates:
        return None

    best_role: int | None = None
    best_score = -1
    for role_id, vocab in _role_term_map().items():
        local_score = -1
        for query_term in role_candidates:
            for known_term in vocab:
                if query_term == known_term:
                    local_score = max(local_score, 200 + len(known_term))
                elif known_term in query_term or query_term in known_term:
                    local_score = max(local_score, 100 + len(known_term))
        if local_score > best_score:
            best_score = local_score
            best_role = role_id

    if best_score < 0:
        return None
    return best_role


def experience_from_years_min(years_min: int | None) -> str | None:
    if years_min is None:
        return None
    for (lo, hi), value in EXPERIENCE_FROM_MIN_YEARS.items():
        if years_min >= lo and (hi is None or years_min < hi):
            return value
    return "moreThan6"


def _area_from_parsed_region(region: str | None) -> int | None:
    if not region:
        return None
    key = region.strip().lower()
    return REGION_NAME_TO_AREA_ID.get(key)


def resume_search_text_for_hh(parsed: dict[str, Any]) -> str | None:
    """
    Текст для параметра HH ``text``.

    Длинные формулировки вроде «найди команду из N человек» дают пустую выдачу API;
    при наличии распознанных ролей и навыков собираем короткую строку поиска.
    """
    raw = parsed.get("text")
    raw_str = raw.strip() if isinstance(raw, str) else ""

    parts: list[str] = []
    seen_lower: set[str] = set()

    def add_chunk(s: str) -> None:
        t = s.strip()
        if not t:
            return
        key = t.lower()
        if key in seen_lower:
            return
        seen_lower.add(key)
        parts.append(t)

    position_terms = parsed.get("position_keywords")
    if isinstance(position_terms, list):
        for item in position_terms:
            if isinstance(item, str):
                add_chunk(item)

    # В legacy-контуре сначала используем канонизированные semantic skills:
    # жаргон заменяется профессиональным каноном/эквивалентами.
    semantic_skill_groups: list[dict[str, Any]] = []
    for group_key in ("must_skills", "should_skills"):
        raw_groups = parsed.get(group_key)
        if isinstance(raw_groups, list):
            semantic_skill_groups.extend([x for x in raw_groups if isinstance(x, dict)])
    if semantic_skill_groups:
        for item in semantic_skill_groups:
            canonical = str(item.get("canonical") or "").strip()
            equivalents = item.get("search_equivalents")
            eq_terms = (
                [str(x).strip() for x in equivalents if str(x).strip()]
                if isinstance(equivalents, list)
                else []
            )
            is_risky = any(rx.search(canonical.lower()) for rx in _RISKY_SKILL_PATTERNS) if canonical else False
            if canonical and not is_risky:
                add_chunk(canonical)
            if is_risky and eq_terms:
                for term in eq_terms[:3]:
                    add_chunk(term)
            elif canonical and not eq_terms:
                add_chunk(canonical)
    else:
        # Fallback на старые поля: hard_skills предпочтительнее legacy skills.
        skills_terms = parsed.get("hard_skills")
        if not isinstance(skills_terms, list) or not skills_terms:
            skills_terms = parsed.get("skills")
        if isinstance(skills_terms, list):
            for item in skills_terms:
                if isinstance(item, str):
                    add_chunk(item)

    if parts:
        return " ".join(parts)
    return raw_str or None


def merge_resume_search_params(
    parsed: dict[str, Any],
    filters: ResumeSearchFilters | dict[str, Any] | None,
    page: int,
    per_page: int,
    query_plan: HHQueryPlan | None = None,
) -> dict[str, Any]:
    """
    Объединяет распознанный запрос и панель фильтров в плоский словарь параметров.
    Явные фильтры из тела запроса перекрывают выведенные из текста значения.
    """
    fdict: dict[str, Any] = {}
    if isinstance(filters, ResumeSearchFilters):
        fdict = filters.model_dump(exclude_none=True)
    elif isinstance(filters, dict):
        fdict = {k: v for k, v in filters.items() if v is not None}

    params: dict[str, Any] = {"page": page, "per_page": per_page}

    text = query_plan.text if query_plan is not None else resume_search_text_for_hh(parsed)
    use_indexed_fields = (
        query_plan is not None
        and settings.hh_query_use_search_field
        and query_plan.parts
    )
    if use_indexed_fields:
        by_field: dict[str, list[str]] = {}
        for field_name, group_text in query_plan.parts:
            if not group_text:
                continue
            by_field.setdefault(field_name, []).append(group_text)
        has_specific = any(f != "everywhere" for f in by_field)
        if has_specific:
            idx = 0
            for field_name, texts in by_field.items():
                hh_field = field_name if field_name != "everywhere" else "resume_text"
                combined = " AND ".join(texts) if len(texts) > 1 else texts[0]
                params[f"text.{idx}.field"] = hh_field
                params[f"text.{idx}.text"] = combined
                params[f"text.{idx}.logic"] = "any"
                idx += 1
        else:
            if text:
                params["text"] = text
    elif text:
        params["text"] = text

    area = fdict.get("area")
    if area is None:
        area = _area_from_parsed_region(parsed.get("region"))
    if area is not None:
        params["area"] = area

    explicit_prof_role = fdict.get("professional_role")
    if explicit_prof_role is not None:
        params["professional_role"] = explicit_prof_role
    elif settings.feature_hh_auto_professional_role:
        inferred_prof_role = infer_professional_role(parsed)
        if inferred_prof_role is not None:
            params["professional_role"] = inferred_prof_role
    if fdict.get("industry") is not None:
        params["industry"] = fdict["industry"]

    skills_ids = fdict.get("skill")
    if skills_ids:
        params["skill"] = skills_ids

    exp = fdict.get("experience")
    if exp is None:
        exp = experience_from_years_min(parsed.get("experience_years_min"))
    if exp is not None:
        params["experience"] = exp

    gender = fdict.get("gender")
    if gender is None:
        gender = parsed.get("gender")
    if gender in ("male", "female"):
        params["gender"] = gender

    age_from = fdict.get("age_from")
    age_to = fdict.get("age_to")
    if age_to is None and parsed.get("age_max") is not None:
        age_to = parsed["age_max"]
    if age_from is not None:
        params["age_from"] = age_from
    if age_to is not None:
        params["age_to"] = age_to

    if fdict.get("salary_from") is not None:
        params["salary_from"] = fdict["salary_from"]
    if fdict.get("salary_to") is not None:
        params["salary_to"] = fdict["salary_to"]
    if fdict.get("currency"):
        params["currency"] = fdict["currency"]

    if fdict.get("period") is not None:
        params["period"] = fdict["period"]
    if fdict.get("relocation") is not None:
        params["relocation"] = fdict["relocation"]
    if fdict.get("education_level") is not None:
        params["education_level"] = fdict["education_level"]
    if fdict.get("employment"):
        params["employment"] = fdict["employment"]

    return params


def flatten_params_for_httpx(params: dict[str, Any]) -> list[tuple[str, Any]]:
    """HH ожидает повторяющиеся ключи для некоторых полей (skill, employment).
    Indexed text keys (text.N.field, text.N.text, text.N.logic) передаются как есть.
    """
    flat: list[tuple[str, Any]] = []
    for key, val in params.items():
        if key == "skill" and isinstance(val, list):
            for s in val:
                flat.append(("skill", s))
        elif key == "employment" and isinstance(val, list):
            for e in val:
                flat.append(("employment", e))
        else:
            flat.append((key, val))
    return flat
