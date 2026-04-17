from __future__ import annotations

from app.services import hh_query_planner
from app.services.mock_llm import parse_query_mock


def test_mock_returns_must_position_and_skills() -> None:
    parsed = parse_query_mock("Python developer 3+ лет Москва вайбкодинг")
    assert parsed["must_position"]
    assert any("разработчик" in p.lower() or "developer" in p.lower() for p in parsed["must_position"])
    assert parsed["must_skills"]
    assert isinstance(parsed["must_skills"][0], dict)
    assert parsed["must_skills"][0]["canonical"] == "Python"
    assert parsed["soft_signals"]
    assert any("вайбкод" in s.lower() for s in parsed["soft_signals"])
    assert isinstance(parsed["should_skills"], list)


def test_mock_boolean_pipeline_builds_plans(monkeypatch) -> None:
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_max_text_length", 2000)
    monkeypatch.setattr(hh_query_planner.settings, "hh_query_use_search_field", False)
    parsed = parse_query_mock("системный аналитик, микросервисы, вайбкодинг ai pair")
    expanded = {}
    plans = hh_query_planner.build_plans(parsed, expanded)
    assert plans, "mock parsed output should produce at least one plan"
    primary_plans = [p for p in plans if p.label.startswith("primary")]
    assert primary_plans
    primary = primary_plans[0]
    assert primary.text
    assert " AND " in primary.text or '"' in primary.text
