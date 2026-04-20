"""Тесты batch-анализа резюме и fallback при сбое парсинга."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import llm_resume_analyzer


def test_analyze_resumes_batch_empty() -> None:
    """Пустой список -> пустой результат."""
    result = llm_resume_analyzer.analyze_resumes_batch({}, [])
    assert result == {}


def test_analyze_resumes_batch_single_no_llm() -> None:
    """При batch_size=1 и без endpoint — вызов analyze_resume (пустой анализ)."""
    resume = {"id": "r1", "hh_resume_id": "hh-1", "title": "Dev", "skills": ["Python"]}
    with patch.object(llm_resume_analyzer, "_call_llm_for_json", return_value=None):
        with patch.object(llm_resume_analyzer, "_call_llm_raw", return_value=None):
            result = llm_resume_analyzer.analyze_resumes_batch(
                {"skills": ["Python"]}, [resume], batch_size=1
            )
    assert "r1" in result or "hh-1" in result
    rid = "r1" if "r1" in result else "hh-1"
    assert result[rid]["llm_score"] is None


def test_analyze_resumes_batch_fallback_on_bad_json() -> None:
    """При битом JSON в batch — fallback на одиночные вызовы."""
    resumes = [
        {"id": "r1", "hh_resume_id": "hh-1", "title": "A", "skills": []},
        {"id": "r2", "hh_resume_id": "hh-2", "title": "B", "skills": []},
    ]
    with patch.object(
        llm_resume_analyzer,
        "_call_llm_raw",
        return_value="not valid json [",
    ):
        with patch.object(
            llm_resume_analyzer,
            "analyze_resume",
            side_effect=lambda req, r, db=None, **_: {
                "llm_score": 50,
                "is_relevant": True,
                "strengths": [],
                "gaps": [],
                "summary": "ok",
            },
        ) as mock_single:
            result = llm_resume_analyzer.analyze_resumes_batch(
                {}, resumes, batch_size=5
            )
    assert mock_single.call_count == 2
    assert len(result) == 2
    assert result["r1"]["llm_score"] == 50
    assert result["r2"]["llm_score"] == 50


def test_analyze_resumes_batch_success() -> None:
    """Корректный JSON-массив возвращает нормализованные анализы."""
    resumes = [
        {"id": "r1", "hh_resume_id": "hh-1", "title": "A", "skills": []},
        {"id": "r2", "hh_resume_id": "hh-2", "title": "B", "skills": []},
    ]
    batch_response = [
        {
            "resume_id": "r1",
            "llm_score": 70,
            "is_relevant": True,
            "strengths": ["s1"],
            "gaps": [],
            "summary": "ok1",
        },
        {
            "resume_id": "r2",
            "llm_score": 60,
            "is_relevant": True,
            "strengths": ["s2"],
            "gaps": [],
            "summary": "ok2",
        },
    ]
    with patch.object(
        llm_resume_analyzer,
        "_call_llm_raw",
        return_value='[{"resume_id":"r1","llm_score":70,"is_relevant":true,"strengths":["s1"],"gaps":[],"summary":"ok1"},{"resume_id":"r2","llm_score":60,"is_relevant":true,"strengths":["s2"],"gaps":[],"summary":"ok2"}]',
    ):
        result = llm_resume_analyzer.analyze_resumes_batch(
            {}, resumes, batch_size=5
        )
    assert result["r1"]["llm_score"] == 70
    assert result["r1"]["strengths"] == ["s1"]
    assert result["r2"]["llm_score"] == 60
    assert result["r2"]["strengths"] == ["s2"]


def test_analyze_resumes_batch_size_respected() -> None:
    """При batch_size=2 и 4 резюме — 2 batch-вызова."""
    resumes = [
        {"id": f"r{i}", "hh_resume_id": f"hh-{i}", "title": "T", "skills": []}
        for i in range(4)
    ]
    responses = [
        '[{"resume_id":"r0","llm_score":50,"is_relevant":true,"strengths":[],"gaps":[],"summary":""},{"resume_id":"r1","llm_score":50,"is_relevant":true,"strengths":[],"gaps":[],"summary":""}]',
        '[{"resume_id":"r2","llm_score":60,"is_relevant":true,"strengths":[],"gaps":[],"summary":""},{"resume_id":"r3","llm_score":60,"is_relevant":true,"strengths":[],"gaps":[],"summary":""}]',
    ]

    with patch.object(
        llm_resume_analyzer,
        "_call_llm_raw",
        side_effect=lambda *_, **__: responses.pop(0) if responses else None,
    ):
        result = llm_resume_analyzer.analyze_resumes_batch(
            {}, resumes, batch_size=2
        )
    assert len(result) == 4
    assert result["r0"]["llm_score"] == 50
    assert result["r3"]["llm_score"] == 60


def test_format_resume_for_prescore_batch_includes_semantic_summary_fragments() -> None:
    resume = {
        "id": "r1",
        "title": "Senior Python Developer",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "experience_years": 7,
        "area": "Москва",
        "about": "Проектирую backend-сервисы и интеграции с внешними API.",
        "work_experience": [
            {
                "position": "Lead Backend Engineer",
                "company": "ACME",
                "description": "Развивал микросервисную архитектуру и высоконагруженные API.",
            },
            {
                "position": "Python Developer",
                "company": "Beta",
                "description": "Вёл доменный модуль рекрутинга, автоматизацию отбора и интеграции.",
            },
        ],
    }

    formatted = llm_resume_analyzer._format_resume_for_prescore_batch(resume)

    assert "[resume_id=r1]" in formatted
    assert "о себе:" in formatted
    assert "последние места работы:" in formatted
    assert "ключевые фрагменты:" in formatted


def test_format_resume_for_prescore_batch_degrades_without_enrichment() -> None:
    resume = {
        "id": "r2",
        "title": "Junior QA",
        "skills": ["Testing"],
        "experience_years": 1,
        "area": "Казань",
    }

    formatted = llm_resume_analyzer._format_resume_for_prescore_batch(resume)

    assert "[resume_id=r2]" in formatted
    assert "должность: Junior QA" in formatted
    assert "навыки: Testing" in formatted
    assert "о себе:" not in formatted
    assert "последние места работы:" not in formatted
