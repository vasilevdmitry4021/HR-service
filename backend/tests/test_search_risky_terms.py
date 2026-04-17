from __future__ import annotations

import pytest

from app.api import search as search_api
from app.services import hh_query_planner


@pytest.mark.asyncio
async def test_fetch_hh_pages_relaxes_risky_group_first(monkeypatch) -> None:
    parsed = {
        "must_position": ["System Analyst"],
        "must_skills": [
            {"canonical": "Python", "synonyms": [], "intent_strength": "required", "query_confidence": 0.9},
            {
                "canonical": "вайбкодинг",
                "synonyms": ["vibe coding"],
                "intent_strength": "preferred",
                "query_confidence": 0.58,
                "search_equivalents": ["AI-assisted coding", "Copilot"],
            },
        ],
        "should_skills": [],
        "soft_signals": [],
        "hard_skills": ["Python"],
        "risky_skills": ["вайбкодинг"],
    }
    plans = hh_query_planner.build_plans(parsed, {})
    primary = next(p for p in plans if p.label == "primary")
    assert any(kind == "should_risky" for kind, _ in primary.groups)

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
        if "вайбкодинг" in text:
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
    assert any(x["risky_groups"] > 0 for x in metrics["queries"] if x["label"] == "primary")
    assert any(x["relax_step"] == 1 for x in metrics["queries"])
    assert any(isinstance(x.get("group_term_sizes"), dict) for x in metrics["queries"])
    assert any(x.get("relaxed") is True for x in metrics["queries"] if x["relax_step"] > 0)


@pytest.mark.asyncio
async def test_fetch_hh_pages_skips_broad_if_target_already_reached(monkeypatch) -> None:
    parsed = {
        "must_position": ["System Analyst"],
        "must_skills": [
            {"canonical": "Python", "synonyms": [], "intent_strength": "required", "query_confidence": 0.9},
        ],
        "should_skills": [],
        "soft_signals": [],
        "hard_skills": ["Python"],
        "risky_skills": [],
    }
    plans = hh_query_planner.build_plans(parsed, {})
    assert any(p.label == "broad" for p in plans)

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
        return [{"id": "r-broad"}], 1

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
    assert all(not label.startswith("broad") for label in call_labels)
    assert all(q["label"] != "broad" for q in metrics["queries"])
