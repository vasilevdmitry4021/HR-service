"""Синхронизация одного источника с подменой вызова Telethon."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from telethon.errors import ChannelPrivateError, FloodWaitError

from app.models.candidate_profile import CandidateProfile
from app.models.telegram_models import TelegramAccount, TelegramMessage, TelegramSource
from app.models.user import User
from app.services import encryption
from telegram_ingestion.services import sync_sources


def _user_and_source(db: Session) -> TelegramSource:
    u = User(
        email=f"sync_{uuid.uuid4().hex[:12]}@example.com",
        password_hash="x",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    acc = TelegramAccount(
        owner_id=u.id,
        api_id="12345",
        encrypted_api_hash=encryption.encrypt_secret("ahash"),
        encrypted_session=encryption.encrypt_secret("session"),
        auth_status="authorized",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    src = TelegramSource(
        account_id=acc.id,
        telegram_id=-1001234567890,
        link="https://t.me/testchannel",
        type="channel",
        display_name="Канал тест",
        access_status="active",
    )
    db.add(src)
    db.commit()
    db.refresh(src)
    return src


def _resume_row(mid: int, text: str) -> dict:
    return {
        "telegram_message_id": mid,
        "text": text,
        "attachments": [],
        "message_link": f"https://t.me/c/1/{mid}",
        "published_at": datetime.now(timezone.utc),
        "author_id": None,
        "author_name": None,
    }


@pytest.mark.integration
def test_sync_empty_source_returns_zero(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_sources, "TELEGRAM_ATTACHMENTS_DIR", str(tmp_path))
    src = _user_and_source(db_session)
    with patch.object(
        sync_sources,
        "fetch_messages_for_source",
        new_callable=AsyncMock,
        return_value=[],
    ):
        proc, cands, err = asyncio.run(sync_sources._sync_one_source(db_session, src))
    db_session.commit()
    assert err is None
    assert proc == 0
    assert cands == 0


@pytest.mark.integration
def test_sync_skips_when_account_not_authorized(db_session: Session) -> None:
    u = User(email=f"u_{uuid.uuid4().hex[:10]}@t.com", password_hash="x")
    db_session.add(u)
    db_session.commit()
    db_session.refresh(u)
    acc = TelegramAccount(
        owner_id=u.id,
        api_id="1",
        encrypted_api_hash=encryption.encrypt_secret("h"),
        encrypted_session=encryption.encrypt_secret("s"),
        auth_status="pending",
    )
    db_session.add(acc)
    db_session.commit()
    db_session.refresh(acc)
    src = TelegramSource(
        account_id=acc.id,
        telegram_id=1,
        link="https://t.me/x",
        type="channel",
        display_name="X",
        access_status="active",
    )
    db_session.add(src)
    db_session.commit()
    db_session.refresh(src)
    proc, cands, err = asyncio.run(sync_sources._sync_one_source(db_session, src))
    assert proc == 0 and cands == 0
    assert err is not None


@pytest.mark.integration
def test_sync_pdf_attachment_long_extract_triggers_resume(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_sources, "TELEGRAM_ATTACHMENTS_DIR", str(tmp_path))
    src = _user_and_source(db_session)
    filler = "Строка текста из PDF для длины. " * 30
    row = {
        "telegram_message_id": 9001,
        "text": "",
        "attachments": [
            {
                "bytes": b"%PDF-1.4 mock",
                "file_type": "pdf",
                "filename": "cv.pdf",
            }
        ],
        "message_link": "https://t.me/c/1/9001",
        "published_at": datetime.now(timezone.utc),
        "author_id": None,
        "author_name": None,
    }
    with (
        patch.object(
            sync_sources,
            "fetch_messages_for_source",
            new_callable=AsyncMock,
            return_value=[row],
        ),
        patch.object(
            sync_sources,
            "extract_text_from_bytes",
            return_value=filler,
        ),
    ):
        proc, cands, err = asyncio.run(sync_sources._sync_one_source(db_session, src))
    db_session.commit()
    assert err is None
    assert proc == 1
    assert cands == 1
    msg = db_session.scalars(
        select(TelegramMessage).where(
            TelegramMessage.telegram_message_id == 9001,
        )
    ).first()
    assert msg is not None
    assert msg.is_resume_candidate is True


@pytest.mark.integration
def test_classifier_disabled_treats_short_text_as_resume(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_sources, "TELEGRAM_ATTACHMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(sync_sources, "TELEGRAM_RESUME_CLASSIFIER_ENABLED", False)
    src = _user_and_source(db_session)
    row = _resume_row(42, "Коротко")
    with patch.object(
        sync_sources,
        "fetch_messages_for_source",
        new_callable=AsyncMock,
        return_value=[row],
    ):
        proc, cands, err = asyncio.run(sync_sources._sync_one_source(db_session, src))
    db_session.commit()
    assert err is None
    assert proc == 1
    assert cands == 1
    msg = db_session.scalars(
        select(TelegramMessage).where(TelegramMessage.telegram_message_id == 42)
    ).first()
    assert msg is not None
    assert msg.is_resume_candidate is True
    assert msg.confidence_score == 1.0


@pytest.mark.integration
def test_dedup_by_email_second_message_merges(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sync_sources, "TELEGRAM_ATTACHMENTS_DIR", str(tmp_path))
    src = _user_and_source(db_session)
    base = (
        "Резюме\nОпыт работы: навыки Python django\n"
        "Контакт unique.dedup@example.com +7 903 000-11-22\n"
    )
    batches = [
        [_resume_row(200, base + " первая версия.")],
        [_resume_row(201, "Другое unique.dedup@example.com вторая версия.")],
    ]

    async def _fetch(*_a, **_kw):
        return batches.pop(0)

    with patch.object(
        sync_sources,
        "fetch_messages_for_source",
        side_effect=_fetch,
    ):
        p1, c1, e1 = asyncio.run(sync_sources._sync_one_source(db_session, src))
        db_session.commit()
        p2, c2, e2 = asyncio.run(sync_sources._sync_one_source(db_session, src))
        db_session.commit()
    assert e1 is None and e2 is None
    assert c1 == 1 and c2 == 0
    assert p1 == 1 and p2 == 1
    n = db_session.scalars(select(CandidateProfile)).all()
    assert len(n) == 1


@pytest.mark.integration
def test_channel_private_sets_access_status(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_sources, "TELEGRAM_ATTACHMENTS_DIR", str(Path.cwd()))
    src = _user_and_source(db_session)
    with patch.object(
        sync_sources,
        "fetch_messages_for_source",
        new_callable=AsyncMock,
        side_effect=ChannelPrivateError(None),
    ):
        proc, cands, err = asyncio.run(sync_sources._sync_one_source(db_session, src))
    db_session.commit()
    db_session.refresh(src)
    assert proc == 0
    assert src.access_status == "access_required"
    assert err is not None


@pytest.mark.integration
def test_flood_wait_maps_to_unavailable(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sync_sources, "TELEGRAM_ATTACHMENTS_DIR", str(Path.cwd()))
    src = _user_and_source(db_session)
    with patch.object(
        sync_sources,
        "fetch_messages_for_source",
        new_callable=AsyncMock,
        side_effect=FloodWaitError(None, capture=120),
    ):
        proc, cands, err = asyncio.run(sync_sources._sync_one_source(db_session, src))
    db_session.commit()
    db_session.refresh(src)
    assert proc == 0
    assert src.access_status == "unavailable"
    assert err and "120" in err
