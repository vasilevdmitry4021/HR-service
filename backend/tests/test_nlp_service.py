from __future__ import annotations

from app.services import mock_llm
from app.services import nlp_service


def test_parse_query_mock_extracts_python_and_moscow() -> None:
    out = mock_llm.parse_query_mock("Нужен Python разработчик в Москве от 3 лет")
    assert "Python" in out["skills"]
    assert out["region"] == "Москва"
    assert out["experience_years_min"] == 3
    assert "разработчик" in out["position_keywords"] or "developer" in out["position_keywords"]


def test_parse_query_mock_age_max() -> None:
    out = mock_llm.parse_query_mock("кандидат до 45 лет")
    assert out["age_max"] == 45


def test_parse_natural_query_returns_params_and_confidence() -> None:
    q = f"Java backend {__import__('uuid').uuid4().hex[:8]}"
    parsed, confidence, ms = nlp_service.parse_natural_query(q)
    assert "Java" in parsed.get("skills", [])
    assert 0.0 < confidence <= 1.0
    assert ms >= 0
