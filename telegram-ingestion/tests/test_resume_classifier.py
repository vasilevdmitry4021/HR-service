"""Граничные случаи эвристического классификатора резюме."""

from __future__ import annotations

import pytest

from telegram_ingestion.services.resume_classifier import classify_resume_text


def test_empty_and_short_text_rejected() -> None:
    assert classify_resume_text("") == (False, 0.0)
    assert classify_resume_text("   ") == (False, 0.0)
    assert classify_resume_text("x" * 49) == (False, 0.0)


def test_long_text_without_signals_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "telegram_ingestion.services.resume_classifier.TELEGRAM_RESUME_CLASSIFIER_MIN_SCORE",
        0.99,
    )
    body = "Случайный длинный текст без явных признаков резюме. " * 8
    ok, score = classify_resume_text(body)
    assert ok is False
    assert score < 0.99


def test_typical_resume_accepted() -> None:
    text = (
        "Резюме Python-разработчик\n"
        "Опыт работы: 5 лет, навыки Django и PostgreSQL\n"
        "Контакт: dev@example.com телефон +7 900 123-45-67\n"
        "GitHub: https://github.com/user linkedin.com/in/x\n"
    )
    ok, score = classify_resume_text(text)
    assert ok is True
    assert score >= 0.6


def test_exactly_fifty_chars_evaluated() -> None:
    text = "a" * 50
    _ok, score = classify_resume_text(text)
    assert score >= 0.0
    assert isinstance(score, float)
