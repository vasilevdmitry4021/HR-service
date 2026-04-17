from __future__ import annotations

from app.services import hh_query_planner


def _parsed() -> dict:
    return {
        "must_position": ["System Analyst", "Системный аналитик"],
        "must_skills": [
            {
                "canonical": "microservices",
                "synonyms": ["микросервисы"],
                "intent_strength": "required",
                "query_confidence": 0.9,
            },
            {
                "canonical": "вайбкодинг",
                "synonyms": ["vibe coding"],
                "intent_strength": "required",
                "query_confidence": 0.45,
            },
            {
                "canonical": "BPMN",
                "synonyms": ['BPMN "2.0"'],
                "intent_strength": "required",
                "query_confidence": 0.88,
            },
        ],
        "should_skills": [
            {
                "canonical": "Cursor",
                "synonyms": ["AI pair programming"],
                "intent_strength": "preferred",
                "query_confidence": 0.66,
            },
        ],
        "soft_signals": ["вайбкодинг", "AI pair"],
        "hard_skills": ["microservices", "BPMN"],
        "risky_skills": ["вайбкодинг", "Cursor"],
    }


def test_build_plans_boolean_and_escaping(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    plans = hh_query_planner.build_plans(_parsed(), {"microservices": ["micro-service:arch"]})
    primary = next(p for p in plans if p.label == "primary")
    assert " AND " in primary.text
    assert " OR " in primary.text
    assert ":" not in primary.text
    assert '"' in primary.text


def test_relax_removes_should_then_must(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    primary = next(p for p in hh_query_planner.build_plans(_parsed(), {}) if p.label == "primary")
    r1 = hh_query_planner.relax(primary, 1)
    r2 = hh_query_planner.relax(primary, 2)
    assert "Cursor" not in r1.text
    assert r2.text.count(" AND ") < r1.text.count(" AND ")


def test_primary_excludes_risky_from_must(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    primary = next(p for p in hh_query_planner.build_plans(_parsed(), {}) if p.label == "primary")
    must_groups = [text for kind, text in primary.groups if kind.startswith("must_")]
    assert all("вайбкодинг" not in text for text in must_groups)
    risky_group = next((text for kind, text in primary.groups if kind == "should_risky"), "")
    assert "вайбкодинг" in risky_group


def test_relax_removes_risky_group_first(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    primary = next(p for p in hh_query_planner.build_plans(_parsed(), {}) if p.label == "primary")
    assert any(kind == "should_risky" for kind, _ in primary.groups)
    r1 = hh_query_planner.relax(primary, 1)
    assert all(kind != "should_risky" for kind, _ in r1.groups)


def test_build_plans_splits_on_text_limit(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 80)
    plans = hh_query_planner.build_plans(_parsed(), {"microservices": ["microservice architecture"] * 5})
    primary_plans = [p for p in plans if p.label.startswith("primary")]
    assert primary_plans
    assert any(p.label.startswith("broad") for p in plans)


def test_build_plans_uses_search_field_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_use_search_field", True)
    plans = hh_query_planner.build_plans(_parsed(), {})
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
    plans = hh_query_planner.build_plans(_parsed(), {})
    assert plans
    primary = next(p for p in plans if p.label == "primary")
    assert primary.parts
    fields_used = {field for field, _ in primary.parts}
    assert fields_used == {"everywhere"}


def test_broad_plan_for_role_sensitive_query_keeps_only_role(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    plans = hh_query_planner.build_plans(_parsed(), {})
    broad = next(p for p in plans if p.label == "broad")
    group_kinds = [kind for kind, _ in broad.groups]
    assert group_kinds == ["role"]


def test_broad_plan_without_role_can_include_single_must(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    parsed = _parsed()
    parsed["must_position"] = []
    parsed["position_keywords"] = []
    plans = hh_query_planner.build_plans(parsed, {})
    broad = next(p for p in plans if p.label == "broad")
    group_kinds = [kind for kind, _ in broad.groups]
    assert len(group_kinds) == 1
    assert group_kinds[0].startswith("must_")
