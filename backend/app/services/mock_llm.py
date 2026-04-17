"""Rule-based stand-in for an LLM when FEATURE_USE_MOCK_LLM is enabled."""

from __future__ import annotations

import re
from typing import Any  # noqa: F401


def parse_query_mock(query: str) -> dict[str, Any]:
    text = query.lower()
    skills: list[str] = []
    tech = [
        ("java", "Java"),
        ("python", "Python"),
        ("javascript", "JavaScript"),
        ("typescript", "TypeScript"),
        ("react", "React"),
        ("go", "Go"),
        ("rust", "Rust"),
        ("kotlin", "Kotlin"),
        ("sql", "SQL"),
        ("postgresql", "PostgreSQL"),
        ("pmp", "PMP"),
        ("микросервис", "микросервисная архитектура"),
        ("microservices", "microservices"),
        ("kubernetes", "Kubernetes"),
        ("docker", "Docker"),
    ]
    for needle, label in tech:
        if needle in text:
            skills.append(label)
    if "микросервис" in text:
        skills.append("microservices")
    if "spring" in text:
        skills.append("Spring Boot")

    exp_min: int | None = None
    for n in range(10, 0, -1):
        if (
            f"от {n} лет" in text
            or f"от {n} год" in text
            or f"{n}+ лет" in text
            or f"{n}+ года" in text
            or f"{n}+ год" in text
            or f"{n} лет опыта" in text
        ):
            exp_min = n
            break

    region: str | None = None
    if "москв" in text:
        region = "Москва"
    elif "спб" in text or "петербург" in text:
        region = "Санкт-Петербург"
    elif "екатеринбург" in text:
        region = "Екатеринбург"
    elif "новосибирск" in text:
        region = "Новосибирск"
    elif "тюмен" in text:
        region = "Тюмень"
    elif "казан" in text:
        region = "Казань"
    elif "нижний" in text or "нижнем" in text:
        region = "Нижний Новгород"

    position_keywords: list[str] = []
    if "разработчик" in text or "developer" in text:
        position_keywords.extend(["разработчик", "developer"])
    if "инженер" in text:
        position_keywords.append("инженер")
    if "аналитик" in text or "analyst" in text:
        position_keywords.extend(["аналитик", "analyst"])
    if "руководитель проект" in text or "менеджер проект" in text or "project manager" in text:
        position_keywords.extend(["руководитель проекта", "менеджер проекта", "project manager", "менеджер проектов"])
    if "архитектор" in text or "architect" in text:
        position_keywords.extend(["архитектор", "architect", "архитектор решений", "системный архитектор", "it-архитектор"])

    gender: str | None = None
    if "женщин" in text or "female" in text:
        gender = "female"
    elif "мужчин" in text or "male" in text:
        gender = "male"

    industry: list[str] = []
    if "ритейл" in text or "retail" in text:
        industry.append("retail")
    if "финанс" in text or "банк" in text:
        industry.append("finance")

    age_max: int | None = None
    m = re.search(r"до\s*(\d{2})\s*лет", text)
    if m:
        age_max = int(m.group(1))

    skills = list(dict.fromkeys(skills))
    position_keywords = list(dict.fromkeys(position_keywords))

    must_position = list(position_keywords)
    must_skills: list[dict[str, Any]] = [
        {"canonical": s, "synonyms": []} for s in skills
    ]
    should_skills: list[dict[str, Any]] = []
    soft_signals: list[str] = []

    soft_markers = [
        ("вайбкод", "вайбкодинг"),
        ("vibe cod", "vibe coding"),
        ("ai pair", "AI pair programming"),
        ("copilot", "GitHub Copilot"),
        ("cursor", "Cursor IDE"),
    ]
    for needle, label in soft_markers:
        if needle in text:
            soft_signals.append(label)
    soft_signals = list(dict.fromkeys(soft_signals))

    return {
        "skills": skills,
        "must_position": must_position,
        "must_skills": must_skills,
        "should_skills": should_skills,
        "soft_signals": soft_signals,
        "experience_years_min": exp_min,
        "region": region,
        "position_keywords": position_keywords,
        "gender": gender,
        "industry": industry,
        "age_max": age_max,
    }
