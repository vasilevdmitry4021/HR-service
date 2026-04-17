from __future__ import annotations

import pytest

from app.services.estaff_candidate_prepare import (
    build_prev_educations_from_norm,
    build_prev_jobs_from_hh_raw,
    prepare_candidate_payload_for_export,
)


def test_build_prev_jobs_parses_years() -> None:
    raw = {
        "experience": [
            {
                "start": {"year": 2020, "month": 6},
                "end": {"year": 2022, "month": 3},
                "company": "ООО Ромашка",
                "position": "Инженер",
            },
        ],
    }
    jobs = build_prev_jobs_from_hh_raw(raw)
    assert len(jobs) == 1
    assert jobs[0]["start_year"] == 2020
    assert jobs[0]["start_month"] == 6
    assert jobs[0]["end_year"] == 2022
    assert jobs[0]["org_name"] == "ООО Ромашка"


def test_build_prev_educations_from_norm() -> None:
    norm = {
        "education": [
            {
                "organization": "МИФИ",
                "speciality": "Физика",
                "year": 2018,
            },
        ],
    }
    edu = build_prev_educations_from_norm(norm)
    assert len(edu) == 1
    assert edu[0]["org_name"] == "МИФИ"
    assert edu[0]["end_year"] == 2018


@pytest.mark.asyncio
async def test_prepare_resolves_location_and_skill() -> None:
    async def fake_fetch(voc_id: str) -> list[dict]:
        if voc_id == "locations":
            return [{"id": 1, "name": "Москва"}]
        if voc_id == "skill_types":
            return [{"id": 10, "name": "Java"}]
        return []

    norm = {
        "hh_resume_id": "rid-1",
        "title": "Разработчик",
        "area": "Москва",
        "experience_years": 3,
        "skills": ["Java"],
        "_raw": {
            "first_name": "Иван",
            "last_name": "Иванов",
            "contact": [{"type": {"id": "email"}, "value": "a@example.com"}],
        },
    }
    payload, warnings = await prepare_candidate_payload_for_export(
        norm,
        server_name="demo",
        api_token="tok",
        fetch_voc_items=fake_fetch,
        candidate_export_key="rid-1",
    )
    assert payload.get("location_id") == "1"
    assert payload.get("city_name") == "Москва"
    assert payload.get("inet_uid") == "rid-1"
    skills = payload.get("skills")
    assert isinstance(skills, list) and len(skills) == 1
    assert skills[0]["type_id"] == "10"
    assert not warnings


