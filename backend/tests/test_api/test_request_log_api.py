"""Интеграционные тесты API журнала запросов."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.request_log import RequestLog
from app.models.user import User


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _register_login(client: TestClient, email: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123"},
    )
    assert r.status_code == 201, r.text
    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert r2.status_code == 200, r2.text
    return {"Authorization": f"Bearer {r2.json()['access_token']}"}


def _make_log_record(
    *,
    db: Session,
    route_tag: str = "search",
    status_code: int = 200,
    duration_ms: int = 100,
    error_type: str | None = None,
    error_message: str | None = None,
    user_id: uuid.UUID | None = None,
    user_email: str | None = None,
    integration_calls: list | None = None,
) -> RequestLog:
    record = RequestLog(
        request_id=str(uuid.uuid4()),
        query_id=str(uuid.uuid4()),
        user_id=user_id,
        user_email=user_email,
        method="POST",
        route="/api/v1/search",
        route_tag=route_tag,
        status_code=status_code,
        duration_ms=duration_ms,
        request_body_summary={"query": "python developer"},
        response_summary={"found": 10},
        search_metrics=None,
        integration_calls=integration_calls,
        error_type=error_type,
        error_message=error_message,
    )
    db.add(record)
    db.flush()
    return record


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

@pytest.fixture
def _clear_request_log(db_session: Session) -> None:
    db_session.execute(text("DELETE FROM request_log"))
    db_session.commit()


@pytest.fixture
def admin_headers(client: TestClient, db_session: Session) -> dict[str, str]:
    email = f"admin_{uuid.uuid4().hex[:10]}@test.com"
    _register_login(client, email)
    user = db_session.query(User).filter(User.email == email).one()
    user.is_admin = True
    db_session.commit()
    return _register_login(client, email)


@pytest.fixture
def user_headers(client: TestClient) -> dict[str, str]:
    email = f"user_{uuid.uuid4().hex[:10]}@test.com"
    return _register_login(client, email)


# ---------------------------------------------------------------------------
# Тесты: доступ
# ---------------------------------------------------------------------------

def test_request_log_list_requires_admin(client: TestClient, user_headers: dict) -> None:
    r = client.get("/api/v1/request-log", headers=user_headers)
    assert r.status_code == 403


def test_request_log_list_requires_auth(client: TestClient) -> None:
    r = client.get("/api/v1/request-log")
    assert r.status_code == 403


def test_request_log_stats_requires_admin(client: TestClient, user_headers: dict) -> None:
    r = client.get("/api/v1/request-log/stats", headers=user_headers)
    assert r.status_code == 403


def test_request_log_errors_requires_admin(client: TestClient, user_headers: dict) -> None:
    r = client.get("/api/v1/request-log/errors", headers=user_headers)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Тесты: список записей
# ---------------------------------------------------------------------------

def test_request_log_list_empty(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    r = client.get("/api/v1/request-log", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_request_log_list_returns_records(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, route_tag="search", status_code=200)
    _make_log_record(db=db_session, route_tag="evaluate", status_code=400, error_type="internal")
    db_session.commit()

    r = client.get("/api/v1/request-log", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


def test_request_log_list_filter_by_route_tag(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, route_tag="search")
    _make_log_record(db=db_session, route_tag="evaluate")
    db_session.commit()

    r = client.get("/api/v1/request-log?route_tag=search", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["route_tag"] == "search"


def test_request_log_list_filter_by_error_type(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, status_code=200)
    _make_log_record(db=db_session, status_code=500, error_type="internal", error_message="Server error")
    db_session.commit()

    r = client.get("/api/v1/request-log?error_type=internal", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["error_type"] == "internal"


def test_request_log_list_filter_by_status(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, status_code=200)
    _make_log_record(db=db_session, status_code=201)
    _make_log_record(db=db_session, status_code=400)
    _make_log_record(db=db_session, status_code=500)
    db_session.commit()

    r = client.get("/api/v1/request-log?status_min=400", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    codes = {item["status_code"] for item in data["items"]}
    assert codes == {400, 500}


def test_request_log_list_pagination(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    for _ in range(5):
        _make_log_record(db=db_session)
    db_session.commit()

    r = client.get("/api/v1/request-log?limit=2&skip=0", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2

    r2 = client.get("/api/v1/request-log?limit=2&skip=4", headers=admin_headers)
    assert r2.status_code == 200
    assert len(r2.json()["items"]) == 1


def test_request_log_list_date_to_includes_selected_day(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    included = _make_log_record(db=db_session)
    included.created_at = datetime(2026, 4, 28, 9, 27, tzinfo=timezone.utc)
    excluded = _make_log_record(db=db_session)
    excluded.created_at = datetime(2026, 4, 29, 0, 0, tzinfo=timezone.utc)
    db_session.commit()

    r = client.get("/api/v1/request-log?date_to=2026-04-28", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["request_id"] == included.request_id
    assert data["items"][0]["request_id"] != excluded.request_id


# ---------------------------------------------------------------------------
# Тесты: детали одной записи
# ---------------------------------------------------------------------------

def test_request_log_entry_found(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    record = _make_log_record(db=db_session, route_tag="search", status_code=200, duration_ms=42)
    db_session.commit()

    r = client.get(f"/api/v1/request-log/{record.request_id}", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["request_id"] == record.request_id
    assert data["route_tag"] == "search"
    assert data["status_code"] == 200
    assert data["duration_ms"] == 42


def test_request_log_entry_not_found(
    client: TestClient,
    admin_headers: dict,
    _clear_request_log: None,
) -> None:
    r = client.get("/api/v1/request-log/nonexistent-request-id", headers=admin_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Тесты: статистика
# ---------------------------------------------------------------------------

def test_request_log_stats_empty(
    client: TestClient,
    admin_headers: dict,
    _clear_request_log: None,
) -> None:
    r = client.get("/api/v1/request-log/stats", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total_requests"] == 0
    assert data["success_count"] == 0
    assert data["error_count"] == 0
    assert data["by_route_tag"] == []
    assert data["by_day"] == []
    assert data["top_errors"] == []
    assert data["integration_summary"] == []


def test_request_log_stats_counts(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, status_code=200, duration_ms=100)
    _make_log_record(db=db_session, status_code=200, duration_ms=200)
    _make_log_record(db=db_session, status_code=500, duration_ms=50, error_type="internal")
    db_session.commit()

    r = client.get("/api/v1/request-log/stats", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total_requests"] == 3
    assert data["success_count"] == 2
    assert data["error_count"] == 1
    assert data["avg_duration_ms"] == pytest.approx((100 + 200 + 50) / 3, rel=1e-3)
    assert len(data["top_errors"]) == 1
    assert data["top_errors"][0]["error_type"] == "internal"


def test_request_log_stats_integration_summary(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    calls = [
        {"system": "hh", "operation": "search", "duration_ms": 300, "status_code": 200, "cached": False},
        {"system": "hh", "operation": "fetch", "duration_ms": 100, "status_code": 200, "cached": True},
        {"system": "llm", "operation": "evaluate", "duration_ms": 500, "status_code": 200, "cached": False},
    ]
    _make_log_record(db=db_session, integration_calls=calls)
    db_session.commit()

    r = client.get("/api/v1/request-log/stats", headers=admin_headers)
    assert r.status_code == 200
    summary = {s["system"]: s for s in r.json()["integration_summary"]}
    assert "hh" in summary
    assert "llm" in summary
    assert summary["hh"]["call_count"] == 2
    assert summary["llm"]["call_count"] == 1


def test_request_log_stats_by_route_tag(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, route_tag="search", status_code=200)
    _make_log_record(db=db_session, route_tag="search", status_code=200)
    _make_log_record(db=db_session, route_tag="evaluate", status_code=500, error_type="internal")
    db_session.commit()

    r = client.get("/api/v1/request-log/stats", headers=admin_headers)
    assert r.status_code == 200
    by_tag = {item["route_tag"]: item for item in r.json()["by_route_tag"]}
    assert by_tag["search"]["count"] == 2
    assert by_tag["search"]["error_count"] == 0
    assert by_tag["evaluate"]["count"] == 1
    assert by_tag["evaluate"]["error_count"] == 1


# ---------------------------------------------------------------------------
# Тесты: сгруппированные ошибки
# ---------------------------------------------------------------------------

def test_request_log_errors_empty(
    client: TestClient,
    admin_headers: dict,
    _clear_request_log: None,
) -> None:
    r = client.get("/api/v1/request-log/errors", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_request_log_errors_grouped(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    for _ in range(3):
        _make_log_record(
            db=db_session,
            route_tag="search",
            status_code=429,
            error_type="hh_rate_limit",
            error_message="Rate limit exceeded",
        )
    _make_log_record(
        db=db_session,
        route_tag="evaluate",
        status_code=500,
        error_type="internal",
        error_message="Unexpected error",
    )
    db_session.commit()

    r = client.get("/api/v1/request-log/errors", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2

    by_type = {item["error_type"]: item for item in data["items"]}
    assert by_type["hh_rate_limit"]["count"] == 3
    assert by_type["internal"]["count"] == 1


def test_request_log_errors_filter_by_type(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, status_code=429, error_type="hh_rate_limit")
    _make_log_record(db=db_session, status_code=500, error_type="internal")
    db_session.commit()

    r = client.get("/api/v1/request-log/errors?error_type=internal", headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["error_type"] == "internal"


def test_request_log_errors_excludes_successful_requests(
    client: TestClient,
    admin_headers: dict,
    db_session: Session,
    _clear_request_log: None,
) -> None:
    _make_log_record(db=db_session, status_code=200, error_type=None)
    _make_log_record(db=db_session, status_code=500, error_type="internal")
    db_session.commit()

    r = client.get("/api/v1/request-log/errors", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 1
