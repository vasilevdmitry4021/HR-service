from __future__ import annotations

from app.services import hh_query_planner


def _parsed() -> dict:
    return {
        "must_position": ["Системный аналитик"],
        "must_skills": [
            {
                "canonical": "Kafka",
                "synonyms": ["Apache Kafka"],
            },
        ],
        "should_skills": [
            {
                "canonical": "микросервисы",
                "synonyms": ["microservices"],
            },
        ],
        "skills": ["Kafka", "микросервисы"],
    }


def test_build_plans_precise_uses_and_for_skills(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    plans = hh_query_planner.build_plans(_parsed(), {}, search_mode="precise")
    primary = next(p for p in plans if p.label == "primary")
    skills_group = next(text for kind, text in primary.groups if kind == "skills")
    assert " AND " in skills_group


def test_build_plans_mass_uses_or_for_skills(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    plans = hh_query_planner.build_plans(_parsed(), {}, search_mode="mass")
    primary = next(p for p in plans if p.label == "primary")
    skills_group = next(text for kind, text in primary.groups if kind == "skills")
    assert " OR " in skills_group
    assert " AND " not in skills_group


def test_build_plans_uses_search_field_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_use_search_field", True)
    plans = hh_query_planner.build_plans(_parsed(), {}, search_mode="precise")
    assert plans
    assert all(p.search_field == "text" for p in plans)
    primary = next(p for p in plans if p.label == "primary")
    assert primary.parts
    fields_used = {field for field, _ in primary.parts}
    assert "position" in fields_used
    assert "skill" in fields_used


def test_build_plans_no_search_field_all_everywhere(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_use_search_field", False)
    plans = hh_query_planner.build_plans(_parsed(), {}, search_mode="precise")
    assert plans
    primary = next(p for p in plans if p.label == "primary")
    assert primary.parts
    fields_used = {field for field, _ in primary.parts}
    assert fields_used == {"everywhere"}


def test_relax_keeps_only_role_group(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    plans = hh_query_planner.build_plans(_parsed(), {}, search_mode="precise")
    primary = next(p for p in plans if p.label == "primary")
    relaxed = hh_query_planner.relax(primary, 1)
    assert [kind for kind, _ in relaxed.groups] == ["role"]
