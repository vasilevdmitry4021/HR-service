"""Юнит-тесты вспомогательных функций request_log_writer (без БД)."""

from __future__ import annotations

import pytest

from app.services.request_log_writer import _mask_sensitive, _mask_tokens_in_text


@pytest.mark.parametrize(
    ("data", "expected_masked_keys"),
    [
        ({"password": "secret", "email": "user@example.com"}, {"password"}),
        ({"api_key": "key123", "query": "developer"}, {"api_key"}),
        ({"client_secret": "cs", "access_token": "at", "refresh_token": "rt"}, {"client_secret", "access_token", "refresh_token"}),
        ({"name": "John", "title": "Python dev"}, set()),
    ],
)
def test_mask_sensitive_replaces_secret_fields(
    data: dict,
    expected_masked_keys: set[str],
) -> None:
    result = _mask_sensitive(data)
    for key in expected_masked_keys:
        assert result[key] == "***", f"Поле '{key}' должно быть замаскировано"
    for key in data:
        if key not in expected_masked_keys:
            assert result[key] == data[key], f"Поле '{key}' не должно изменяться"


def test_mask_sensitive_does_not_mutate_original() -> None:
    original = {"password": "secret", "name": "test"}
    _mask_sensitive(original)
    assert original["password"] == "secret"


@pytest.mark.parametrize(
    ("text", "expected_masked"),
    [
        (None, None),
        ("нет токена здесь", "нет токена здесь"),
        ("Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature", "Bearer ***"),
        ("Authorization: Bearer abc123==", "Authorization: Bearer ***"),
        ("bearer TOKEN_VALUE more text", "bearer *** more text"),
    ],
)
def test_mask_tokens_in_text(text: str | None, expected_masked: str | None) -> None:
    result = _mask_tokens_in_text(text)
    assert result == expected_masked
