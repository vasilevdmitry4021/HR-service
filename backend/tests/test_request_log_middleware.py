"""Юнит-тесты вспомогательных функций RequestLogMiddleware (без БД)."""

from __future__ import annotations

import pytest

from app.middleware.request_log import (
    _classify_error_type,
    _route_tag,
    _should_skip,
    _tracked_route_tag,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/health", True),
        ("/docs", True),
        ("/openapi.json", True),
        ("/redoc", True),
        ("/docs/some-path", True),
        ("/static/file.js", True),
        ("/api/v1/request-log", True),
        ("/api/v1/request-log/errors", True),
        ("/api/v1/search", False),
        ("/api/v1/auth/login", False),
    ],
)
def test_should_skip(path: str, expected: bool) -> None:
    assert _should_skip(path) is expected


@pytest.mark.parametrize(
    ("method", "path", "expected_tag"),
    [
        ("POST", "/api/v1/search", "search"),
        ("POST", "/api/v1/search/parse", "parse"),
        ("POST", "/api/v1/search/snapshot-1/evaluate", "evaluate"),
        ("POST", "/api/v1/search/snapshot-1/evaluate/start", "evaluate"),
        ("POST", "/api/v1/search/snapshot-1/analyze", "analyze"),
        ("POST", "/api/v1/search/snapshot-1/analyze/start", "analyze"),
        ("POST", "/api/v1/candidates/abc123/analyze", "analyze"),
        ("GET", "/api/v1/search/snapshot-1/evaluate/progress", None),
        ("POST", "/api/v1/search/snapshot-1/evaluate/cancel", None),
        ("GET", "/api/v1/favorites", None),
        ("POST", "/api/v1/estaff/export", None),
    ],
)
def test_tracked_route_tag(
    method: str,
    path: str,
    expected_tag: str | None,
) -> None:
    assert _tracked_route_tag(method, path) == expected_tag


@pytest.mark.parametrize(
    ("path", "expected_tag"),
    [
        ("/api/v1/search", "search"),
        ("/api/v1/search/parse", "parse"),
        ("/api/v1/search/evaluate", "evaluate"),
        ("/api/v1/search/analyze", "analyze"),
        ("/api/v1/estaff/export", "estaff_export"),
        ("/api/v1/estaff/vacancies", "estaff_vacancies"),
        ("/api/v1/llm/settings", "llm_settings"),
        ("/api/v1/auth/login", "auth"),
        ("/api/v1/history", "other"),
        ("/api/v1/request-log", "other"),
    ],
)
def test_route_tag(path: str, expected_tag: str) -> None:
    assert _route_tag(path) == expected_tag


@pytest.mark.parametrize(
    ("status_code", "error_type_from_state", "expected"),
    [
        (200, None, None),
        (201, None, None),
        (400, None, None),
        (401, None, "hh_permission"),
        (403, None, "hh_permission"),
        (429, None, "hh_rate_limit"),
        (500, None, "internal"),
        (503, None, "internal"),
        (400, "llm_timeout", "llm_timeout"),
        (200, "estaff_connection", "estaff_connection"),
    ],
)
def test_classify_error_type(
    status_code: int,
    error_type_from_state: str | None,
    expected: str | None,
) -> None:
    assert _classify_error_type(status_code, error_type_from_state) == expected
