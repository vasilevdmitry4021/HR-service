from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.estaff_client import (
    build_estaff_base_url,
    hh_normalized_resume_to_estaff_payload,
    normalize_vacancies_payload,
)


def test_build_estaff_base_url_full_host() -> None:
    assert build_estaff_base_url("krit.e-staff.ru") == "https://krit.e-staff.ru"


def test_build_estaff_base_url_short_subdomain() -> None:
    assert build_estaff_base_url("krit") == "https://krit.e-staff.ru"


def test_build_estaff_base_url_short_with_port() -> None:
    assert build_estaff_base_url("krit:8443") == "https://krit.e-staff.ru:8443"


def test_build_estaff_base_url_full_https() -> None:
    assert (
        build_estaff_base_url("https://custom.example.com/path/")
        == "https://custom.example.com/path"
    )


def test_hh_normalized_resume_to_estaff_payload_minimal() -> None:
    norm = {
        "full_name": "Иванов Иван",
        "title": "Разработчик",
        "hh_resume_id": "abc",
        "hh_resume_url": "https://hh.ru/resume/abc",
        "area": "Москва",
        "skills": ["Python"],
        "salary": {"amount": 200000, "currency": "RUR"},
        "_raw": {
            "last_name": "Иванов",
            "first_name": "Иван",
            "contact": [
                {
                    "type": {"id": "email"},
                    "value": "a@example.com",
                },
                {
                    "type": {"id": "cell"},
                    "value": "+79991234567",
                },
            ],
        },
    }
    p = hh_normalized_resume_to_estaff_payload(norm)
    assert p["email"] == "a@example.com"
    assert p["mobile_phone"] == "+79991234567"
    assert p["desired_position_name"] == "Разработчик"
    assert p["lastname"] == "Иванов"
    assert p["firstname"] == "Иван"
    assert p["salary"] == 200000


def test_hh_normalized_resume_to_estaff_payload_fio_placeholders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "estaff_fio_placeholder_enabled", True)
    monkeypatch.setattr(settings, "estaff_fio_placeholder_firstname", "ПодставкаИмя")
    monkeypatch.setattr(settings, "estaff_fio_placeholder_lastname", "ПодставкаФам")
    monkeypatch.setattr(settings, "estaff_fio_placeholder_middlename", "ПодставкаОтч")
    monkeypatch.setattr(settings, "estaff_contact_placeholder_email", "stub@example.test")
    monkeypatch.setattr(settings, "estaff_contact_placeholder_mobile", "+79990001122")
    norm = {
        "title": "Инженер",
        "_raw": {"contact": []},
    }
    p = hh_normalized_resume_to_estaff_payload(norm)
    assert p["firstname"] == "ПодставкаИмя"
    assert p["lastname"] == "ПодставкаФам"
    assert p["middlename"] == "ПодставкаОтч"
    assert p["email"] == "stub@example.test"
    assert p["mobile_phone"] == "+79990001122"
    assert p["desired_position_name"] == "Инженер"


def test_normalize_vacancies_payload_root_list() -> None:
    rows = normalize_vacancies_payload(
        [
            {"id": "1", "title": "A", "number": "10"},
            {"uuid": "2", "name": "B"},
        ],
    )
    assert len(rows) == 2
    assert rows[0]["id"] == "1"
    assert rows[0]["title"] == "A"
    assert rows[0]["subtitle"] == "№ 10"
    assert rows[1]["id"] == "2"
    assert rows[1]["title"] == "B"


def test_normalize_vacancies_payload_wrapped() -> None:
    rows = normalize_vacancies_payload(
        {"data": [{"id": "x", "title": "T"}]},
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "x"


def test_normalize_vacancies_payload_success_false() -> None:
    rows = normalize_vacancies_payload(
        {"success": False, "vacancies": [{"id": 1, "name": "X"}]},
    )
    assert rows == []


def test_normalize_vacancies_payload_estaff_shape() -> None:
    rows = normalize_vacancies_payload(
        {
            "success": True,
            "vacancies": [
                {"id": 42, "name": "Инженер", "start_date": "2025-01-01T00:00:00Z"},
            ],
        },
    )
    assert len(rows) == 1
    assert rows[0]["id"] == "42"
    assert rows[0]["title"] == "Инженер"


@pytest.mark.asyncio
async def test_fetch_open_vacancies_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.services import estaff_client

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    rows, elapsed = await estaff_client.fetch_open_vacancies(
        "demo",
        "t",
        min_start_date_iso="2026-01-01T00:00:00.000Z",
        max_start_date_iso="2026-12-31T23:59:59.999Z",
    )
    assert len(rows) == 3
    assert rows[0]["id"] == "mock-vac-1"
    assert elapsed >= 0


@pytest.mark.asyncio
async def test_fetch_open_vacancies_post_uses_bearer_and_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings
    from app.services import estaff_client

    monkeypatch.setattr(settings, "feature_use_mock_estaff", False)
    monkeypatch.setattr(settings, "estaff_vacancies_path", "/api/vacancy/find")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = {
        "success": True,
        "vacancies": [{"id": 1, "name": "V1"}],
    }

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.estaff_client.httpx.AsyncClient", return_value=mock_client):
        rows, _ = await estaff_client.fetch_open_vacancies(
            "krit.e-staff.ru",
            "tok",
            min_start_date_iso="2026-03-01T00:00:00.000Z",
            max_start_date_iso="2026-03-31T23:59:59.999Z",
        )

    assert len(rows) == 1
    assert rows[0]["id"] == "1"
    mock_client.post.assert_called_once()
    call_kw = mock_client.post.call_args
    assert call_kw[0][0] == "https://krit.e-staff.ru/api/vacancy/find"
    headers = call_kw[1]["headers"]
    assert headers["Authorization"] == "Bearer tok"
    flt = call_kw[1]["json"]["filter"]
    assert flt == {
        "min_start_date": "2026-03-01T00:00:00.000Z",
        "max_start_date": "2026-03-31T23:59:59.999Z",
    }


@pytest.mark.asyncio
async def test_create_candidate_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.services import estaff_client

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    cid, elapsed = await estaff_client.create_candidate_in_estaff(
        "x",
        "token",
        {"lastname": "Иванов", "email": "t@example.com"},
        vacancy_id="100",
    )
    assert cid and "mock-estaff" in cid
    assert elapsed >= 0


@pytest.mark.asyncio
async def test_fetch_get_voc_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import settings
    from app.services import estaff_client

    monkeypatch.setattr(settings, "feature_use_mock_estaff", True)
    items = await estaff_client.fetch_get_voc("krit", "tok", "locations")
    assert len(items) >= 1
    assert any(str(it.get("name", "")).lower() == "москва" for it in items)


@pytest.mark.asyncio
async def test_fetch_get_voc_post_uses_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings
    from app.services import estaff_client

    monkeypatch.setattr(settings, "feature_use_mock_estaff", False)
    monkeypatch.setattr(settings, "estaff_get_voc_path", "/api/base/get_voc")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = {
        "success": True,
        "skill_types": [{"id": 5, "name": "Go"}],
    }

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.estaff_client.httpx.AsyncClient", return_value=mock_client):
        items = await estaff_client.fetch_get_voc(
            "krit.e-staff.ru",
            "tok",
            "skill_types",
        )

    assert len(items) == 1
    assert items[0]["id"] == 5
    mock_client.post.assert_called_once()
    assert mock_client.post.call_args[0][0].endswith("/api/base/get_voc")
    assert mock_client.post.call_args[1]["json"] == {"voc": {"id": "skill_types"}}


@pytest.mark.asyncio
async def test_create_candidate_post_wraps_candidate_and_vacancy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings
    from app.services import estaff_client

    monkeypatch.setattr(settings, "feature_use_mock_estaff", False)
    monkeypatch.setattr(settings, "estaff_create_candidate_path", "/api/candidate/add")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.is_success = True
    mock_response.json.return_value = {"id": 999}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    body = {"lastname": "Петров", "firstname": "Пётр"}
    with patch("app.services.estaff_client.httpx.AsyncClient", return_value=mock_client):
        cid, _ = await estaff_client.create_candidate_in_estaff(
            "krit.e-staff.ru",
            "tok",
            body,
            vacancy_id="55",
        )

    assert cid == "999"
    mock_client.post.assert_called_once()
    sent = mock_client.post.call_args[1]["json"]
    assert sent == {
        "candidate": {
            **body,
            "user_login": "dmitriy.vasiliev@krit.pro",
        },
        "vacancy": {"id": 55},
    }
    assert mock_client.post.call_args[1]["headers"]["Authorization"] == "Bearer tok"
