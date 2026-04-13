from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def test_estaff_credentials_status_and_put(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.get("/api/v1/estaff/credentials", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"configured": False}

    r2 = client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "secret-token"},
    )
    assert r2.status_code == 200

    r3 = client.get("/api/v1/estaff/credentials", headers=auth_headers)
    assert r3.status_code == 200
    assert r3.json() == {"configured": True}


def test_estaff_export_stores_user_message_on_estaff_client_error(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings
    from app.services.estaff_client import EStaffClientError

    monkeypatch.setattr(settings, "feature_use_mock_estaff", False)

    async def _fail_create(*_a, **_kw):
        raise EStaffClientError(
            422,
            "Короткое сообщение для пользователя",
            "HTTP 422: " + "детально " * 800,
        )

    monkeypatch.setattr(
        "app.api.estaff.create_candidate_in_estaff",
        _fail_create,
    )

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    resume_id = "hh-mock-001"
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {"hh_resume_id": resume_id, "vacancy_id": "1"},
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["results"][0]["status"] == "error"
    assert data["results"][0]["error_message"] == "Короткое сообщение для пользователя"
    assert data["results"][0].get("error_stage") == "estaff_api"

    r2 = client.get(
        f"/api/v1/estaff/exports/{resume_id}",
        headers=auth_headers,
    )
    assert r2.status_code == 200
    latest = r2.json()
    assert latest["found"] is True
    assert latest["error_message"] == "Короткое сообщение для пользователя"
    assert "HTTP 422" not in (latest.get("error_message") or "")


def test_estaff_export_accepts_candidate_id_field(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {"candidate_id": "hh-by-candidate-id-1", "vacancy_id": "mock-vac-1"},
            ],
        },
    )
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert row["candidate_id"] == "hh-by-candidate-id-1"


def test_estaff_export_include_hr_llm_bundle_adds_attachments(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    monkeypatch.setattr(settings, "feature_use_mock_hh", True)
    monkeypatch.setattr(settings, "hr_public_base_url", "https://hr.example.com")
    monkeypatch.setattr(settings, "estaff_hr_bundle_attachment_type_id", "hr-note-type")

    captured: list[dict] = []

    async def _capture(
        server_name: str,
        api_token: str,
        body: dict,
        *,
        user_login: str,
        vacancy_id: str | None = None,
    ):
        captured.append(dict(body))
        return "mock-with-attachment", 0.01

    monkeypatch.setattr(
        "app.api.estaff.create_candidate_in_estaff",
        _capture,
    )

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    resume_id = "hh-mock-002"
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {
                    "hh_resume_id": resume_id,
                    "vacancy_id": "mock-vac-1",
                    "include_hr_llm_bundle": True,
                    "hr_llm_summary": "Сильный <b>кандидат</b>",
                    "hr_llm_score": 72,
                    "hr_search_query": "Python разработчик",
                },
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "success"
    assert len(captured) == 1
    body = captured[0]
    atts = body.get("attachments")
    assert isinstance(atts, list) and len(atts) == 1
    att = atts[0]
    assert att.get("content_type") == "text/html"
    assert att.get("type_id") == "hr-note-type"
    assert att.get("file_name") == "hr-service-note.html"
    html_data = att.get("html_data") or ""
    assert "https://hr.example.com/candidates/" in html_data
    assert resume_id in html_data or resume_id.replace("-", "") in html_data
    assert "q=" in html_data and "Python" in html_data
    assert "Сильный" in html_data
    assert "<b>" not in html_data
    assert "&lt;b&gt;" in html_data
    assert "72" in html_data
    assert "Вывод" in html_data


def test_estaff_export_hr_llm_analysis_structured_in_html(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """hr_llm_analysis: в HTML попадают релевантность, списки и вывод."""
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    monkeypatch.setattr(settings, "feature_use_mock_hh", True)
    monkeypatch.setattr(settings, "hr_public_base_url", "https://hr.example.com")
    monkeypatch.setattr(settings, "estaff_hr_bundle_attachment_type_id", "hr-note-type")

    captured: list[dict] = []

    async def _capture(
        server_name: str,
        api_token: str,
        body: dict,
        *,
        user_login: str,
        vacancy_id: str | None = None,
    ):
        captured.append(dict(body))
        return "mock-structured", 0.01

    monkeypatch.setattr(
        "app.api.estaff.create_candidate_in_estaff",
        _capture,
    )

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    resume_id = "hh-mock-003"
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {
                    "hh_resume_id": resume_id,
                    "vacancy_id": "mock-vac-1",
                    "include_hr_llm_bundle": True,
                    "hr_llm_analysis": {
                        "llm_score": 80,
                        "is_relevant": True,
                        "strengths": ["Опыт в Python", "Английский B2"],
                        "gaps": ["Нет Kubernetes"],
                        "summary": "Итоговый вывод по кандидату",
                    },
                },
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "success"
    html_data = captured[0]["attachments"][0].get("html_data") or ""
    assert "80" in html_data
    assert "релевантен" in html_data.lower()
    assert "Опыт в Python" in html_data
    assert "Нет Kubernetes" in html_data
    assert "Итоговый вывод по кандидату" in html_data
    assert "Сильные стороны" in html_data
    assert "Пробелы и риски" in html_data
    assert "Вывод" in html_data


def test_estaff_export_hr_llm_from_favorite_when_client_omits_llm_fields(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """include_hr_llm_bundle без hr_llm_* в теле — балл и сводка из записи избранного."""
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    monkeypatch.setattr(settings, "feature_use_mock_hh", True)
    monkeypatch.setattr(settings, "hr_public_base_url", "https://hr.example.com")
    monkeypatch.setattr(settings, "estaff_hr_bundle_attachment_type_id", "hr-note-type")

    captured: list[dict] = []

    async def _capture(
        server_name: str,
        api_token: str,
        body: dict,
        *,
        user_login: str,
        vacancy_id: str | None = None,
    ):
        captured.append(dict(body))
        return "mock-fav-bundle", 0.01

    monkeypatch.setattr(
        "app.api.estaff.create_candidate_in_estaff",
        _capture,
    )

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    resume_id = "hh-mock-fav-llm-only"
    fav = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": resume_id,
            "title_snapshot": "Title",
            "notes": "",
            "llm_score": 91,
            "llm_summary": "Сводка только в избранном",
        },
    )
    assert fav.status_code == 201

    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {
                    "candidate_id": resume_id,
                    "vacancy_id": "mock-vac-1",
                    "include_hr_llm_bundle": True,
                },
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "success"
    assert len(captured) == 1
    atts = captured[0].get("attachments")
    assert isinstance(atts, list) and len(atts) == 1
    html_data = atts[0].get("html_data") or ""
    assert "91" in html_data
    assert "Сводка только в избранном" in html_data
    assert "Вывод" in html_data


def test_estaff_export_hr_llm_from_favorite_llm_analysis_json(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Полный JSON оценки в избранном без полей клиента — все секции во вложении."""
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    monkeypatch.setattr(settings, "feature_use_mock_hh", True)
    monkeypatch.setattr(settings, "hr_public_base_url", "https://hr.example.com")
    monkeypatch.setattr(settings, "estaff_hr_bundle_attachment_type_id", "hr-note-type")

    captured: list[dict] = []

    async def _capture(
        server_name: str,
        api_token: str,
        body: dict,
        *,
        user_login: str,
        vacancy_id: str | None = None,
    ):
        captured.append(dict(body))
        return "mock-fav-json", 0.01

    monkeypatch.setattr(
        "app.api.estaff.create_candidate_in_estaff",
        _capture,
    )

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    resume_id = "hh-mock-004"
    fav = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": resume_id,
            "title_snapshot": "T",
            "notes": "",
            "llm_score": 55,
            "llm_summary": "Кратко",
            "llm_analysis": {
                "llm_score": 55,
                "is_relevant": False,
                "strengths": ["Из избранного сильная"],
                "gaps": ["Из избранного пробел"],
                "summary": "Вывод из JSON избранного",
            },
        },
    )
    assert fav.status_code == 201

    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {
                    "candidate_id": resume_id,
                    "vacancy_id": "mock-vac-1",
                    "include_hr_llm_bundle": True,
                },
            ],
        },
    )
    assert r.status_code == 200
    assert r.json()["results"][0]["status"] == "success"
    html_data = captured[0]["attachments"][0].get("html_data") or ""
    assert "Из избранного сильная" in html_data
    assert "Из избранного пробел" in html_data
    assert "Вывод из JSON избранного" in html_data
    assert "не релевантен" in html_data.lower() or "не релевант" in html_data.lower()


def test_estaff_export_mock_hh_and_estaff(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [
                {"hh_resume_id": "hh-mock-001", "vacancy_id": "mock-vac-1"},
            ],
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["results"]) == 1
    row = data["results"][0]
    assert row["status"] == "success"
    assert row["candidate_id"] == "hh-mock-001"
    assert row.get("hh_resume_id") == "hh-mock-001"
    assert row["estaff_candidate_id"]

    r2 = client.get(
        "/api/v1/estaff/exports/hh-mock-001",
        headers=auth_headers,
    )
    assert r2.status_code == 200
    latest = r2.json()
    assert latest["found"] is True
    assert latest["status"] == "success"


def test_estaff_export_requires_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [{"hh_resume_id": "hh-mock-001", "vacancy_id": "v1"}],
        },
    )
    assert r.status_code == 503


def test_estaff_export_requires_vacancy_id(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={"user_login": "hr.user", "items": [{"hh_resume_id": "hh-mock-001"}]},
    )
    assert r.status_code == 422


def test_estaff_export_requires_user_login(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "items": [{"hh_resume_id": "hh-mock-001", "vacancy_id": "v1"}],
        },
    )
    assert r.status_code == 422


def test_estaff_user_check_mock_success(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    r = client.post(
        "/api/v1/estaff/user/check",
        headers=auth_headers,
        json={"login": "hr.user"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is True
    assert r.json()["login"] == "hr.user"


def test_estaff_user_check_not_found(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _not_found(*_a, **_kw):
        return None, 0.01

    monkeypatch.setattr(
        "app.api.estaff.fetch_user_by_login",
        _not_found,
    )
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    r = client.post(
        "/api/v1/estaff/user/check",
        headers=auth_headers,
        json={"login": "missing.user"},
    )
    assert r.status_code == 200
    assert r.json() == {"valid": False, "login": "missing.user", "user_name": None}


def test_estaff_vacancies_mock(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)

    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )

    r = client.get("/api/v1/estaff/vacancies", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert len(data["items"]) >= 1
    assert data["items"][0]["id"]
    assert data["items"][0]["title"]


def test_estaff_vacancies_requires_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.get("/api/v1/estaff/vacancies", headers=auth_headers)
    assert r.status_code == 503


def test_estaff_vacancies_partial_date_query_bad_request(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    r = client.get(
        "/api/v1/estaff/vacancies?min_start_date=2026-01-01",
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_estaff_exports_latest_batch_empty(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/estaff/exports/latest-batch",
        headers=auth_headers,
        json={"hh_resume_ids": []},
    )
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_estaff_exports_latest_batch_not_found_and_success(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    rid = "hh-mock-003"
    client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [{"hh_resume_id": rid, "vacancy_id": "mock-vac-1"}],
        },
    )
    r = client.post(
        "/api/v1/estaff/exports/latest-batch",
        headers=auth_headers,
        json={"hh_resume_ids": ["no-such-resume", rid]},
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["hh_resume_id"] == "no-such-resume"
    assert data["items"][0]["found"] is False
    assert data["items"][1]["hh_resume_id"] == rid
    assert data["items"][1]["found"] is True
    assert data["items"][1]["status"] == "success"


def test_estaff_exports_latest_batch_returns_latest_row(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    rid = "hh-mock-004"
    client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={"user_login": "hr.user", "items": [{"hh_resume_id": rid, "vacancy_id": "v1"}]},
    )
    monkeypatch.setattr(settings, "feature_use_mock_estaff", False)
    from app.services.estaff_client import EStaffClientError

    async def _fail(*_a, **_kw):
        raise EStaffClientError(500, "fail", "detail")

    monkeypatch.setattr(
        "app.api.estaff.create_candidate_in_estaff",
        _fail,
    )
    client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={"user_login": "hr.user", "items": [{"hh_resume_id": rid, "vacancy_id": "v2"}]},
    )
    r = client.post(
        "/api/v1/estaff/exports/latest-batch",
        headers=auth_headers,
        json={"hh_resume_ids": [rid]},
    )
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["found"] is True
    assert item["status"] == "error"


def test_estaff_exports_latest_batch_other_user_isolated(
    client: TestClient,
    auth_headers: dict[str, str],
    unique_email: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    rid = "hh-mock-005"
    client.post(
        "/api/v1/estaff/export",
        headers=auth_headers,
        json={
            "user_login": "hr.user",
            "items": [{"hh_resume_id": rid, "vacancy_id": "mock-vac-1"}],
        },
    )
    email_b = f"b_{unique_email}"
    assert client.post(
        "/api/v1/auth/register",
        json={"email": email_b, "password": "testpass123"},
    ).status_code == 201
    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": email_b, "password": "testpass123"},
    )
    assert login_b.status_code == 200
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}
    r = client.post(
        "/api/v1/estaff/exports/latest-batch",
        headers=headers_b,
        json={"hh_resume_ids": [rid]},
    )
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["hh_resume_id"] == rid
    assert item["found"] is False


def test_estaff_exports_latest_batch_too_many_ids(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    from app.schemas.estaff import MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS

    ids = [f"id{i}" for i in range(MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS + 1)]
    r = client.post(
        "/api/v1/estaff/exports/latest-batch",
        headers=auth_headers,
        json={"hh_resume_ids": ids},
    )
    assert r.status_code == 422


def test_estaff_vacancies_with_explicit_date_range(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    client.put(
        "/api/v1/estaff/credentials",
        headers=auth_headers,
        json={"server_name": "demo", "api_token": "t"},
    )
    r = client.get(
        "/api/v1/estaff/vacancies"
        "?min_start_date=2025-06-01&max_start_date=2025-06-30",
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) >= 1
