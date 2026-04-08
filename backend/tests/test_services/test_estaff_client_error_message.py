"""Сообщения для пользователя из JSON ошибок e-staff."""

from __future__ import annotations

import pytest

from app.services.estaff_client import extract_estaff_error_message_for_user


@pytest.mark.parametrize(
    ("payload", "expected_substring"),
    [
        ({"error": {"message": "Поле firstname обязательно"}}, "firstname"),
        ({"message": "Некорректный запрос"}, "Некорректный"),
        ({"detail": "Вакансия не найдена"}, "Вакансия"),
        ({"error": "Сервис недоступен"}, "Сервис"),
        ("Текст ошибки\r\nвторая строка", "Текст ошибки вторая"),
    ],
)
def test_extract_estaff_error_message_for_user(payload: object, expected_substring: str) -> None:
    out = extract_estaff_error_message_for_user(payload)
    assert out is not None
    assert expected_substring in out


def test_extract_estaff_error_message_skips_html() -> None:
    assert extract_estaff_error_message_for_user({"message": "<html><body>fail</body></html>"}) is None


def test_extract_estaff_error_message_truncates_long_string() -> None:
    long_msg = "x" * 600
    out = extract_estaff_error_message_for_user({"message": long_msg}, max_len=100)
    assert out is not None
    assert len(out) <= 100
    assert out.endswith("…")
