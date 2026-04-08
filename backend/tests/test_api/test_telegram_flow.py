"""Сквозные проверки API Telegram, поиска и карточки (без реального Telethon)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.telegram import AUTH_AUTHORIZED
from app.config import settings
from app.models.candidate_profile import CandidateProfile
from app.models.telegram_models import (
    TelegramAccount,
    TelegramMessage,
    TelegramMessageAttachment,
    TelegramSource,
)
from app.services import encryption
from app.services import search_snapshot_cache


@pytest.fixture(autouse=True)
def _reset_snapshots() -> None:
    search_snapshot_cache.reset_snapshots_for_tests()
    yield
    search_snapshot_cache.reset_snapshots_for_tests()


def _enable_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "feature_use_telegram_source", True)


def _user_id(client: TestClient, auth_headers: dict[str, str]) -> uuid.UUID:
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200, r.text
    return uuid.UUID(r.json()["id"])


def _authorized_account(db: Session, owner_id: uuid.UUID) -> TelegramAccount:
    acc = TelegramAccount(
        owner_id=owner_id,
        api_id="12345",
        encrypted_api_hash=encryption.encrypt_secret("hash"),
        encrypted_session=encryption.encrypt_secret("sess"),
        phone_hint="+7***",
        auth_status=AUTH_AUTHORIZED,
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.mark.integration
def test_add_source_invalid_link_no_probe(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_telegram(monkeypatch)
    uid = _user_id(client, auth_headers)
    _authorized_account(db_session, uid)
    with patch("app.api.telegram.telethon_import_error", return_value=None):
        r = client.post(
            "/api/v1/telegram/sources",
            headers=auth_headers,
            json={"link": "https://example.com/channel", "display_name": ""},
        )
    assert r.status_code == 201
    body = r.json()
    assert body["access_status"] == "invalid"
    assert "Неподдерживаемый" in (body.get("error_message") or "")


@pytest.mark.integration
def test_add_source_probed_and_sync_run(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_telegram(monkeypatch)
    uid = _user_id(client, auth_headers)
    _authorized_account(db_session, uid)

    async def fake_probe(*_a: object, **_k: object) -> tuple:
        return (999001, "channel", "Test Channel", "active", None)

    with patch("app.api.telegram.telethon_import_error", return_value=None):
        with patch(
            "app.api.telegram._probe_telegram_source",
            new_callable=AsyncMock,
            side_effect=fake_probe,
        ):
            r = client.post(
                "/api/v1/telegram/sources",
                headers=auth_headers,
                json={"link": "https://t.me/testchannel", "display_name": ""},
            )
    assert r.status_code == 201
    src = r.json()
    assert src["access_status"] == "active"
    assert src["telegram_id"] == 999001

    sid = uuid.UUID(src["id"])
    r2 = client.post(
        f"/api/v1/telegram/sources/{sid}/sync",
        headers=auth_headers,
    )
    assert r2.status_code == 200
    run = r2.json()
    assert run["status"] == "queued"
    assert run["source_id"] == str(sid)

    r3 = client.get("/api/v1/telegram/sync-runs", headers=auth_headers)
    assert r3.status_code == 200
    assert len(r3.json()) >= 1


@pytest.mark.integration
def test_validate_source_updates_access(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_telegram(monkeypatch)
    uid = _user_id(client, auth_headers)
    acc = _authorized_account(db_session, uid)
    src = TelegramSource(
        account_id=acc.id,
        telegram_id=0,
        link="bad",
        type="channel",
        display_name="X",
        access_status="invalid",
        is_enabled=True,
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)

    async def fake_probe(*_a: object, **_k: object) -> tuple:
        return (888, "group", "G", "active", None)

    with patch("app.api.telegram.telethon_import_error", return_value=None):
        with patch(
            "app.api.telegram._probe_telegram_source",
            new_callable=AsyncMock,
            side_effect=fake_probe,
        ):
            r = client.post(
                f"/api/v1/telegram/sources/{src.id}/validate",
                headers=auth_headers,
            )
    assert r.status_code == 200
    assert r.json()["access_status"] == "active"
    assert r.json()["telegram_id"] == 888


@pytest.mark.integration
def test_telegram_message_unique_per_source(
    db_session: Session,
    auth_headers: dict[str, str],
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_telegram(monkeypatch)
    uid = _user_id(client, auth_headers)
    acc = _authorized_account(db_session, uid)
    src = TelegramSource(
        account_id=acc.id,
        telegram_id=1,
        link="https://t.me/x",
        type="channel",
        display_name="X",
        access_status="active",
        is_enabled=True,
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)
    m1 = TelegramMessage(
        source_id=src.id,
        telegram_message_id=42,
        parse_status="ok",
        is_resume_candidate=True,
    )
    db_session.add(m1)
    db_session.commit()
    m2 = TelegramMessage(
        source_id=src.id,
        telegram_message_id=42,
        parse_status="ok",
        is_resume_candidate=False,
    )
    db_session.add(m2)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


@pytest.mark.integration
def test_search_telegram_and_all_with_profile(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_telegram(monkeypatch)
    uid = _user_id(client, auth_headers)
    acc = _authorized_account(db_session, uid)
    src = TelegramSource(
        account_id=acc.id,
        telegram_id=2,
        link="https://t.me/jobs",
        type="channel",
        display_name="Jobs",
        access_status="active",
        is_enabled=True,
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)

    msg_id = uuid.uuid4()
    msg = TelegramMessage(
        id=msg_id,
        source_id=src.id,
        telegram_message_id=100,
        text="Senior Golang developer",
        parse_status="parsed",
        is_resume_candidate=True,
    )
    db_session.add(msg)
    db_session.commit()

    prof = CandidateProfile(
        id=uuid.uuid4(),
        source_type="telegram",
        source_resume_id=str(msg_id),
        source_url="https://t.me/jobs/100",
        full_name="Пётр Го",
        title="Golang разработчик",
        area="Санкт-Петербург",
        experience_years=6,
        skills=["Golang"],
        raw_text="Senior Golang developer docker kubernetes",
        normalized_payload={
            "telegram": {
                "sources": [
                    {
                        "source_display_name": "Jobs",
                        "message_link": "https://t.me/jobs/100",
                    }
                ],
                "attachments": [
                    {
                        "filename": "cv.txt",
                        "extracted_preview": "описание проекта на Go",
                    }
                ],
            }
        },
        parse_confidence=0.85,
    )
    db_session.add(prof)
    db_session.commit()

    att = TelegramMessageAttachment(
        message_id=msg_id,
        file_type="txt",
        file_path="/tmp/x.txt",
        extracted_text="описание проекта на Go",
    )
    db_session.add(att)
    db_session.commit()

    r_tg = client.post(
        "/api/v1/search",
        headers=auth_headers,
        json={
            "query": "Golang",
            "source_scope": "telegram",
            "page": 0,
            "per_page": 20,
        },
    )
    assert r_tg.status_code == 200
    data_tg = r_tg.json()
    assert data_tg["source_scope"] == "telegram"
    assert data_tg["found"] >= 1
    ids_tg = {x["id"] for x in data_tg["items"]}
    assert str(prof.id) in ids_tg
    row = next(x for x in data_tg["items"] if x["id"] == str(prof.id))
    assert row.get("source_type") == "telegram"
    assert len(row.get("telegram_attachments") or []) >= 1

    async def fake_hh_search(*_a: object, **_k: object) -> tuple:
        return (
            [
                {
                    "id": "hh-mock-all",
                    "hh_resume_id": "hh-mock-all",
                    "title": "Разработчик",
                    "full_name": "Анна",
                    "skills": ["Golang"],
                    "area": "Москва",
                    "experience_years": 5,
                }
            ],
            1,
        )

    with patch(
        "app.api.search.hh_client.search_resumes",
        new_callable=AsyncMock,
        side_effect=fake_hh_search,
    ):
        r_all = client.post(
            "/api/v1/search",
            headers=auth_headers,
            json={
                "query": "Golang разработчик",
                "source_scope": "all",
                "page": 0,
                "per_page": 20,
            },
        )
    assert r_all.status_code == 200
    data_all = r_all.json()
    assert data_all["source_scope"] == "all"
    ids_all = {x["id"] for x in data_all["items"]}
    assert str(prof.id) in ids_all
    assert "hh-mock-all" in ids_all


@pytest.mark.integration
def test_candidate_detail_telegram(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_telegram(monkeypatch)
    uid = _user_id(client, auth_headers)
    acc = _authorized_account(db_session, uid)
    src = TelegramSource(
        account_id=acc.id,
        telegram_id=3,
        link="https://t.me/c",
        type="channel",
        display_name="C",
        access_status="active",
        is_enabled=True,
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)
    msg_id = uuid.uuid4()
    msg = TelegramMessage(
        id=msg_id,
        source_id=src.id,
        telegram_message_id=200,
        text="текст",
        parse_status="parsed",
        is_resume_candidate=True,
    )
    db_session.add(msg)
    db_session.commit()
    prof = CandidateProfile(
        id=uuid.uuid4(),
        source_type="telegram",
        source_resume_id=str(msg_id),
        source_url="https://t.me/c/200",
        full_name="Деталь Тест",
        title="Аналитик",
        area="Казань",
        experience_years=3,
        skills=["SQL"],
        raw_text="полный текст сообщения",
        normalized_payload={
            "telegram": {
                "sources": [{"display_name": "Канал C", "message_link": "https://t.me/c/200"}],
                "attachments": [],
            }
        },
        parse_confidence=0.7,
    )
    db_session.add(prof)
    db_session.commit()

    r = client.get(f"/api/v1/candidates/{prof.id}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["source_type"] == "telegram"
    assert d.get("raw_message_text")
    assert len(d.get("telegram_sources") or []) == 1
    assert d["telegram_sources"][0].get("source_display_name") == "Канал C"


@pytest.mark.integration
def test_telegram_status_when_disconnected(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_telegram(monkeypatch)
    r = client.get("/api/v1/telegram/status", headers=auth_headers)
    assert r.status_code == 200
    j = r.json()
    assert j.get("feature_enabled") is True
    assert j.get("connected") is False
