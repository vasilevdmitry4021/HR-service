from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.schemas.search_filters import ResumeSearchFilters
from app.services.hh_query_planner import HHQueryPlan

if TYPE_CHECKING:
    from app.services.hh_client import HHProfessionalRoleReference

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
_AREA_ALIASES: dict[str, int] = {
    "мск": 1,
    "moscow": 1,
    "москва и область": 1,
    "санкт петербург": 2,
    "санктпетербург": 2,
    "спб": 2,
    "питер": 2,
    "петербург": 2,
    "saint petersburg": 2,
    "spb": 2,
    "екб": 3,
    "екат": 3,
    "новосиб": 4,
    "нск": 4,
}

EXPERIENCE_FROM_MIN_YEARS: dict[tuple[int, int | None], str] = {
    (0, 1): "noExperience",
    (1, 3): "between1And3",
    (3, 6): "between3And6",
    (6, None): "moreThan6",
}

_ANALYST_GENERAL_TERMS = {"аналитик", "analyst"}
_CANONICAL_ANALYST_NAMES = (
    "системный аналитик",
    "бизнес-аналитик",
    "bi-аналитик, аналитик данных",
)


def _normalize_role_term(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_role_candidates(parsed: dict[str, Any]) -> list[str]:
    role_candidates: list[str] = []
    for field_name in ("must_position", "position_keywords"):
        terms = parsed.get(field_name)
        if isinstance(terms, list):
            for term in terms:
                if isinstance(term, str):
                    normalized = _normalize_role_term(term)
                    if normalized:
                        role_candidates.append(normalized)
    return role_candidates


def _unique_role_ids(role_ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for role_id in role_ids:
        if role_id in seen:
            continue
        seen.add(role_id)
        out.append(role_id)
    return out


def resolve_professional_roles(
    parsed: dict[str, Any],
    professional_roles_reference: HHProfessionalRoleReference | None,
) -> tuple[list[int], list[dict[str, Any]]]:
    if professional_roles_reference is None:
        return [], []
    role_candidates = _collect_role_candidates(parsed)
    if not role_candidates:
        return [], []

    normalized_index = professional_roles_reference.normalized_role_name_to_ids
    if not normalized_index:
        return [], []

    role_scores: dict[int, int] = {}
    match_debug: list[dict[str, Any]] = []
    for query_term in role_candidates:
        matched_names: list[str] = []
        for role_name, role_ids in normalized_index.items():
            score = -1
            if query_term == role_name:
                score = 200 + len(role_name)
            elif role_name in query_term or query_term in role_name:
                score = 100 + len(role_name)
            if score < 0:
                continue
            matched_names.append(role_name)
            for role_id in role_ids:
                role_scores[role_id] = max(role_scores.get(role_id, 0), score)
        if matched_names:
            matched_ids: list[int] = []
            for role_name in matched_names:
                matched_ids.extend(normalized_index.get(role_name, ()))
            match_debug.append(
                {
                    "term": query_term,
                    "strategy": "names_first",
                    "matched_role_names": sorted(set(matched_names)),
                    "matched_role_ids": _unique_role_ids(sorted(matched_ids)),
                }
            )

    contains_generic_analyst = any(term in _ANALYST_GENERAL_TERMS for term in role_candidates)
    if contains_generic_analyst:
        analyst_role_ids: list[int] = []
        analyst_role_names: list[str] = []
        canonical_terms = [_normalize_role_term(name) for name in _CANONICAL_ANALYST_NAMES]
        for canonical_name in canonical_terms:
            canonical_matched: list[int] = []
            for role_name, role_ids in normalized_index.items():
                if (
                    canonical_name == role_name
                    or canonical_name in role_name
                    or role_name in canonical_name
                ):
                    analyst_role_names.append(role_name)
                    canonical_matched.extend(role_ids)
                    for role_id in role_ids:
                        role_scores[role_id] = max(
                            role_scores.get(role_id, 0),
                            150 + len(role_name),
                        )
            analyst_role_ids.extend(_unique_role_ids(canonical_matched))
        analyst_role_ids = _unique_role_ids(analyst_role_ids)
        if analyst_role_ids:
            match_debug.append(
                {
                    "term": "аналитик",
                    "strategy": "canonical_analyst_fanout",
                    "matched_role_names": sorted(set(analyst_role_names)),
                    "matched_role_ids": analyst_role_ids,
                }
            )
            return analyst_role_ids, match_debug

    if not role_scores:
        return [], match_debug

    best_role = max(role_scores, key=role_scores.get)
    return [best_role], match_debug


def infer_professional_roles(
    parsed: dict[str, Any],
    professional_roles_reference: HHProfessionalRoleReference | None = None,
) -> list[int]:
    roles, _ = resolve_professional_roles(parsed, professional_roles_reference)
    return roles


def infer_professional_role(
    parsed: dict[str, Any],
    professional_roles_reference: HHProfessionalRoleReference | None = None,
) -> int | None:
    roles = infer_professional_roles(parsed, professional_roles_reference)
    return roles[0] if roles else None


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
    key = re.sub(r"[^a-zа-я0-9]+", " ", str(region or "").strip().lower().replace("ё", "е"))
    key = re.sub(r"\s+", " ", key).strip()
    if not key:
        return None
    return REGION_NAME_TO_AREA_ID.get(key) or _AREA_ALIASES.get(key)


def resolve_area_priority(
    parsed: dict[str, Any],
    filters: ResumeSearchFilters | dict[str, Any] | None,
) -> tuple[list[int] | None, str]:
    """
    Единая политика региона для HH:
    1) Явный region из панели фильтров имеет максимальный приоритет.
    2) Если panel-region не задан, используем регион, извлеченный из текста запроса.
    """
    fdict: dict[str, Any] = {}
    if isinstance(filters, ResumeSearchFilters):
        fdict = filters.model_dump(exclude_none=True)
    elif isinstance(filters, dict):
        fdict = {k: v for k, v in filters.items() if v is not None}

    area = fdict.get("area")
    if area is not None:
        if isinstance(area, list):
            area_ids = []
            for raw in area:
                try:
                    area_ids.append(int(raw))
                except (TypeError, ValueError):
                    continue
            uniq = list(dict.fromkeys(area_ids))
            if uniq:
                return uniq, "panel"
            return None, "none"
        try:
            return [int(area)], "panel"
        except (TypeError, ValueError):
            return None, "none"
    parsed_area = _area_from_parsed_region(parsed.get("region"))
    if parsed_area is not None:
        return [parsed_area], "parsed_region"
    return None, "none"


def _skill_terms_from_parsed(parsed: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add_term(value: str) -> None:
        normalized = _normalize_role_term(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        terms.append(value.strip())

    semantic_skill_groups: list[dict[str, Any]] = []
    for group_key in ("must_skills", "should_skills"):
        raw_groups = parsed.get(group_key)
        if isinstance(raw_groups, list):
            semantic_skill_groups.extend([x for x in raw_groups if isinstance(x, dict)])
    for item in semantic_skill_groups:
        canonical = str(item.get("canonical") or "").strip()
        if canonical and not settings.feature_skill_synonyms_enabled:
            add_term(canonical)
            continue
        equivalents = item.get("search_equivalents")
        eq_terms = (
            [str(x).strip() for x in equivalents if str(x).strip()]
            if isinstance(equivalents, list)
            else []
        )
        is_risky = any(rx.search(canonical.lower()) for rx in _RISKY_SKILL_PATTERNS) if canonical else False
        if canonical and not is_risky:
            add_term(canonical)
        if is_risky and eq_terms:
            for term in eq_terms[:3]:
                add_term(term)
        elif canonical and not eq_terms:
            add_term(canonical)

    if terms:
        return terms

    fallback_terms = parsed.get("hard_skills")
    if not isinstance(fallback_terms, list) or not fallback_terms:
        fallback_terms = parsed.get("skills")
    if isinstance(fallback_terms, list):
        for item in fallback_terms:
            if isinstance(item, str):
                add_term(item)
    return terms


def resume_search_text_for_hh(
    parsed: dict[str, Any],
    *,
    search_mode: str = "precise",
    include_role_terms: bool = True,
) -> str | None:
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

    if include_role_terms:
        position_terms = parsed.get("position_keywords")
        if isinstance(position_terms, list):
            for item in position_terms:
                if isinstance(item, str):
                    add_chunk(item)

    skill_terms = _skill_terms_from_parsed(parsed)
    for term in skill_terms:
        add_chunk(term)

    if parts:
        operator = " AND " if search_mode == "precise" else " OR "
        return operator.join(parts)
    return raw_str or None


def merge_resume_search_params(
    parsed: dict[str, Any],
    filters: ResumeSearchFilters | dict[str, Any] | None,
    page: int,
    per_page: int,
    query_plan: HHQueryPlan | None = None,
    search_mode: str = "precise",
    professional_role_ids: list[int] | None = None,
    professional_roles_reference: HHProfessionalRoleReference | None = None,
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

    text = (
        query_plan.text
        if query_plan is not None
        else resume_search_text_for_hh(parsed, search_mode=search_mode, include_role_terms=False)
    )
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

    area_ids, _area_source = resolve_area_priority(parsed, filters)
    if area_ids:
        params["area"] = area_ids

    explicit_prof_role = fdict.get("professional_role")
    if explicit_prof_role is not None:
        params["professional_role"] = explicit_prof_role
    elif professional_role_ids:
        params["professional_role"] = [int(x) for x in professional_role_ids if isinstance(x, int)]
    elif settings.feature_hh_auto_professional_role:
        inferred_prof_roles = infer_professional_roles(parsed, professional_roles_reference)
        if inferred_prof_roles:
            params["professional_role"] = inferred_prof_roles
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
        if key in {"skill", "professional_role", "area"} and isinstance(val, list):
            for s in val:
                flat.append((key, s))
        elif key == "employment" and isinstance(val, list):
            for e in val:
                flat.append(("employment", e))
        else:
            flat.append((key, val))
    return flat
