from __future__ import annotations

import pytest

from app.api import search as search_api
from app.services import hh_query_planner


@pytest.mark.asyncio
async def test_fetch_hh_pages_relax_removes_skills_group(monkeypatch) -> None:
    parsed = {
        "must_position": ["System Analyst"],
        "must_skills": [
            {"canonical": "Python", "synonyms": []},
        ],
        "should_skills": [],
    }
    plans = hh_query_planner.build_plans(parsed, {}, search_mode="precise")
    primary = next(p for p in plans if p.label == "primary")
    assert any(kind == "skills" for kind, _ in primary.groups)

    monkeypatch.setattr(search_api.settings, "hh_query_relax_max_steps", 2)
    monkeypatch.setattr(search_api.settings, "search_recall_target_min", 4)

    async def fake_search_resumes(
        access,
        parsed_payload,
        filters,
        page,
        per_page,
        *,
        query_plan=None,
        db=None,
        hh_token_user_id=None,
    ):
        _ = access, parsed_payload, filters, db, hh_token_user_id, per_page
        text = (query_plan.text if query_plan else "").lower()
        if page > 0:
            return [], 0
        if "python" in text:
            return [], 0
        return [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}, {"id": "r4"}], 4

    monkeypatch.setattr(search_api.hh_client, "search_resumes", fake_search_resumes)
    rows, found_total, loaded, metrics = await search_api._fetch_hh_resume_pages(
        access=None,
        parsed=parsed,
        filters={},
        plans=plans,
        max_resumes=20,
        per_page=20,
    )
    assert len(rows) == 4
    assert found_total >= 4
    assert loaded == 4
    assert metrics["relax_used"] is True
    assert any(x["relax_step"] == 1 for x in metrics["queries"])
    assert any(isinstance(x.get("group_term_sizes"), dict) for x in metrics["queries"])
    assert any(x.get("relaxed") is True for x in metrics["queries"] if x["relax_step"] > 0)


@pytest.mark.asyncio
async def test_fetch_hh_pages_uses_only_primary_in_new_planner(monkeypatch) -> None:
    parsed = {
        "must_position": ["System Analyst"],
        "must_skills": [
            {"canonical": "Python", "synonyms": []},
        ],
        "should_skills": [],
    }
    plans = hh_query_planner.build_plans(parsed, {}, search_mode="precise")
    assert len(plans) == 1
    assert plans[0].label == "primary"

    monkeypatch.setattr(search_api.settings, "search_recall_target_min", 2)

    call_labels: list[str] = []

    async def fake_search_resumes(
        access,
        parsed_payload,
        filters,
        page,
        per_page,
        *,
        query_plan=None,
        db=None,
        hh_token_user_id=None,
    ):
        _ = access, parsed_payload, filters, per_page, db, hh_token_user_id
        if page > 0:
            return [], 0
        label = (query_plan.label if query_plan is not None else "legacy")
        call_labels.append(label)
        if label.startswith("primary"):
            return [{"id": "r1"}, {"id": "r2"}], 2
        return [{"id": "r-extra"}], 1

    monkeypatch.setattr(search_api.hh_client, "search_resumes", fake_search_resumes)
    rows, found_total, loaded, metrics = await search_api._fetch_hh_resume_pages(
        access=None,
        parsed=parsed,
        filters={},
        plans=plans,
        max_resumes=20,
        per_page=20,
    )
    assert found_total >= 2
    assert loaded == 2
    assert len(rows) == 2
    assert call_labels == ["primary"]
    assert all(q["label"] == "primary" for q in metrics["queries"])
