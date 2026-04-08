"""Тесты пост-фильтрации по числовым границам и фильтрам соответствия."""

from __future__ import annotations

import pytest

from app.services import post_filter


def test_apply_strict_filters_experience_hide() -> None:
    """Кандидат с experience_years=8 при experience_years_min=9 не попадает в выдачу (hide)."""
    items = [
        {"id": "1", "experience_years": 8, "age": 30},
        {"id": "2", "experience_years": 9, "age": 32},
        {"id": "3", "experience_years": 10, "age": 35},
    ]
    parsed = {"experience_years_min": 9}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 2
    assert all(r["experience_years"] >= 9 for r in out)
    assert not any(r["id"] == "1" for r in out)


def test_apply_strict_filters_experience_demote() -> None:
    """В режиме demote не прошедшие получают strict_match=False."""
    items = [
        {"id": "1", "experience_years": 8, "age": 30},
        {"id": "2", "experience_years": 9, "age": 32},
    ]
    parsed = {"experience_years_min": 9}
    out = post_filter.apply_strict_filters(items, parsed, mode="demote")
    assert len(out) == 2
    by_id = {r["id"]: r for r in out}
    assert by_id["1"]["strict_match"] is False
    assert by_id["2"]["strict_match"] is True


def test_apply_strict_filters_age_min() -> None:
    """age_min: кандидат моложе отсекается."""
    items = [
        {"id": "1", "age": 24, "experience_years": 5},
        {"id": "2", "age": 25, "experience_years": 5},
    ]
    parsed = {"age_min": 25}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 1
    assert out[0]["id"] == "2"


def test_apply_strict_filters_age_max() -> None:
    """age_max: кандидат старше отсекается."""
    items = [
        {"id": "1", "age": 34, "experience_years": 5},
        {"id": "2", "age": 35, "experience_years": 5},
        {"id": "3", "age": 36, "experience_years": 5},
    ]
    parsed = {"age_max": 35}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 2
    assert all(r["age"] <= 35 for r in out)
    assert not any(r["id"] == "3" for r in out)


def test_apply_strict_filters_salary_from() -> None:
    """salary_from: кандидат с зарплатой ниже отсекается."""
    items = [
        {"id": "1", "salary": {"amount": 150000, "currency": "RUR"}},
        {"id": "2", "salary": {"amount": 200000, "currency": "RUR"}},
    ]
    parsed = {"salary_from": 200000}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 1
    assert out[0]["id"] == "2"


def test_apply_strict_filters_no_bounds_passthrough() -> None:
    """Без числовых границ все проходят без изменений."""
    items = [{"id": "1", "experience_years": 5}]
    parsed = {}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 1
    assert out[0]["id"] == "1"


def test_apply_strict_filters_missing_age_fails() -> None:
    """Кандидат без возраста не проходит при наличии age_min."""
    items = [{"id": "1", "experience_years": 10}]
    parsed = {"age_min": 25}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 0


def test_apply_strict_filters_skills_match() -> None:
    """Кандидат с нужным навыком проходит фильтр."""
    items = [
        {"id": "1", "skills": ["Java", "Spring Boot"], "title": "Java Developer"},
        {"id": "2", "skills": ["Python", "Django"], "title": "Python Developer"},
        {"id": "3", "skills": ["JavaScript", "React"], "title": "Frontend Developer"},
    ]
    parsed = {"skills": ["Java"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 1
    assert out[0]["id"] == "1"


def test_apply_strict_filters_skills_no_match() -> None:
    """Кандидат без требуемых навыков отсеивается."""
    items = [
        {"id": "1", "skills": ["Python", "Django"], "title": "Python Developer"},
    ]
    parsed = {"skills": ["Java", "Kotlin"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 0


def test_apply_strict_filters_skills_synonym() -> None:
    """Навыки сопоставляются с учётом синонимов (js = javascript)."""
    items = [
        {"id": "1", "skills": ["js", "React"], "title": "Frontend Developer"},
    ]
    parsed = {"skills": ["JavaScript"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 1
    assert out[0]["id"] == "1"


def test_apply_strict_filters_position_match() -> None:
    """Кандидат с подходящей должностью проходит фильтр."""
    items = [
        {"id": "1", "skills": ["Java"], "title": "Java Developer"},
        {"id": "2", "skills": ["Python"], "title": "Журналист"},
        {"id": "3", "skills": ["Go"], "title": "Go Programmer"},
    ]
    parsed = {"position_keywords": ["разработчик", "developer"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 2
    ids = {r["id"] for r in out}
    assert "1" in ids
    assert "3" in ids
    assert "2" not in ids


def test_apply_strict_filters_position_no_match() -> None:
    """Кандидат с неподходящей должностью отсеивается."""
    items = [
        {"id": "1", "skills": ["writing"], "title": "Журналист"},
        {"id": "2", "skills": ["design"], "title": "Дизайнер"},
    ]
    parsed = {"position_keywords": ["разработчик", "developer"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 0


def test_apply_strict_filters_skills_and_position_combined() -> None:
    """Фильтрация по навыкам И должности одновременно."""
    items = [
        {"id": "1", "skills": ["Java", "Spring"], "title": "Java Developer"},
        {"id": "2", "skills": ["Java"], "title": "Журналист"},
        {"id": "3", "skills": ["Python"], "title": "Python Developer"},
    ]
    parsed = {"skills": ["Java"], "position_keywords": ["разработчик", "developer"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 1
    assert out[0]["id"] == "1"


def test_apply_strict_filters_empty_skills_passes() -> None:
    """Без указания навыков все кандидаты проходят."""
    items = [
        {"id": "1", "skills": ["Java"], "title": "Developer"},
        {"id": "2", "skills": [], "title": "Manager"},
    ]
    parsed = {"position_keywords": ["developer", "manager"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 2


def test_apply_strict_filters_demote_skills() -> None:
    """В режиме demote кандидат без навыков получает strict_match=False."""
    items = [
        {"id": "1", "skills": ["Java"], "title": "Developer"},
        {"id": "2", "skills": ["Python"], "title": "Developer"},
    ]
    parsed = {"skills": ["Java"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="demote")
    assert len(out) == 2
    by_id = {r["id"]: r for r in out}
    assert by_id["1"]["strict_match"] is True
    assert by_id["2"]["strict_match"] is False


def test_apply_strict_filters_title_different_tech() -> None:
    """Frontend-разработчик отсеивается при поиске Java."""
    items = [
        {"id": "1", "skills": [], "title": "Java Developer"},
        {"id": "2", "skills": [], "title": "Frontend-разработчик"},
        {"id": "3", "skills": [], "title": "Python Developer"},
        {"id": "4", "skills": [], "title": "Разработчик"},
    ]
    parsed = {"skills": ["Java"], "position_keywords": ["разработчик", "developer"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    ids = {r["id"] for r in out}
    assert "1" in ids
    assert "2" not in ids
    assert "3" not in ids
    assert "4" in ids


def test_apply_strict_filters_title_matching_tech() -> None:
    """Java Developer проходит при поиске Java."""
    items = [
        {"id": "1", "skills": [], "title": "Java Developer"},
        {"id": "2", "skills": [], "title": "Senior Java разработчик"},
    ]
    parsed = {"skills": ["Java"], "position_keywords": ["разработчик", "developer"]}
    out = post_filter.apply_strict_filters(items, parsed, mode="hide")
    assert len(out) == 2
