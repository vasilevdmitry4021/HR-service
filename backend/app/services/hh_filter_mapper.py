from __future__ import annotations

from typing import Any

from app.schemas.search_filters import ResumeSearchFilters

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

    for seq_key in ("position_keywords", "skills"):
        seq = parsed.get(seq_key)
        if not isinstance(seq, list):
            continue
        for item in seq:
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

    text = resume_search_text_for_hh(parsed)
    if text:
        params["text"] = text

    area = fdict.get("area")
    if area is None:
        area = _area_from_parsed_region(parsed.get("region"))
    if area is not None:
        params["area"] = area

    if fdict.get("professional_role") is not None:
        params["professional_role"] = fdict["professional_role"]
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
    """HH ожидает повторяющиеся ключи для некоторых полей (skill, employment)."""
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
