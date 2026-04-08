"""Загрузка сообщений и документов-вложений через Telethon."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class TelegramIngestionError(RuntimeError):
    """Ошибка уровня сервиса с явным статусом для записи telegram_sources."""

    def __init__(self, access_status: str, message: str) -> None:
        self.access_status = access_status
        super().__init__(message)


def map_telegram_access_error(exc: BaseException) -> tuple[str, str]:
    """Сопоставить исключение Telethon со статусом источника и текстом ошибки."""
    from telethon.errors import (
        ChannelPrivateError,
        ChatAdminRequiredError,
        FloodWaitError,
        InviteHashExpiredError,
        InviteHashInvalidError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
        UserNotParticipantError,
    )

    msg = (str(exc).strip() or type(exc).__name__)[:500]
    if isinstance(
        exc,
        (UsernameNotOccupiedError, UsernameInvalidError, InviteHashInvalidError),
    ):
        return "invalid", msg
    if isinstance(
        exc,
        (
            ChannelPrivateError,
            UserNotParticipantError,
            ChatAdminRequiredError,
            InviteHashExpiredError,
        ),
    ):
        return "access_required", msg
    if isinstance(exc, FloodWaitError):
        return "unavailable", f"Лимит Telegram, повторите через {exc.seconds} с"
    return "unavailable", msg


def normalize_telegram_link_input(raw: str) -> str | None:
    """Привести ввод пользователя к строке для client.get_entity или None."""
    s = (raw or "").strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://"):
        if re.match(r"https?://(t(elegram)?\.me)(/|$)", s, re.I):
            return s
        return None
    if s.startswith("@"):
        return s
    if re.match(r"^[A-Za-z][A-Za-z0-9_]{3,31}$", s):
        return f"https://t.me/{s}"
    if re.match(r"^t\.me/", low) or re.match(r"^telegram\.me/", low):
        return f"https://{s}"
    if s.startswith("+"):
        return f"https://t.me/{s}"
    if low.startswith("joinchat/"):
        return f"https://t.me/{s}"
    if low.startswith("tg://"):
        return s
    return None


async def fetch_messages_for_source(
    api_id: int,
    api_hash: str,
    session_string: str,
    telegram_id: int,
    *,
    limit: int,
    min_id: int | None,
    allowed_extensions: frozenset[str],
    max_attachment_bytes: int,
) -> list[dict[str, Any]]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.types import DocumentAttributeFilename, MessageMediaDocument

    from telegram_ingestion.services.attachment_text import normalize_extension

    out: list[dict[str, Any]] = []
    client = TelegramClient(StringSession(session_string or ""), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            logger.warning("telegram session not authorized")
            raise TelegramIngestionError(
                "access_required",
                "Сессия Telegram не авторизована",
            )
        entity = await client.get_entity(telegram_id)
        kwargs: dict[str, Any] = {"limit": limit}
        if min_id:
            kwargs["min_id"] = int(min_id)
        async for msg in client.iter_messages(entity, **kwargs):
            if not msg or not getattr(msg, "id", None):
                continue
            text = getattr(msg, "message", None) or ""
            if not isinstance(text, str):
                text = str(text)
            dt = getattr(msg, "date", None)
            published = None
            if dt is not None:
                if dt.tzinfo is None:
                    published = dt.replace(tzinfo=timezone.utc)
                else:
                    published = dt.astimezone(timezone.utc)
            sender = await msg.get_sender()
            author_name = None
            author_id = None
            if sender is not None:
                author_id = int(getattr(sender, "id", 0) or 0) or None
                fn = getattr(sender, "first_name", None) or ""
                ln = getattr(sender, "last_name", None) or ""
                un = getattr(sender, "username", None) or ""
                author_name = (f"{fn} {ln}".strip() or un or None)
            link = None
            ch = getattr(entity, "username", None)
            if ch:
                link = f"https://t.me/{ch}/{msg.id}"

            attachments: list[dict[str, Any]] = []
            media = getattr(msg, "media", None)
            if isinstance(media, MessageMediaDocument) and media.document:
                doc = media.document
                fname = None
                for attr in getattr(doc, "attributes", None) or []:
                    if isinstance(attr, DocumentAttributeFilename):
                        fname = attr.file_name
                        break
                mime = getattr(doc, "mime_type", None) or ""
                ext = normalize_extension(fname, mime)
                size = int(getattr(doc, "size", 0) or 0)
                if (
                    ext
                    and ext in allowed_extensions
                    and size > 0
                    and size <= max_attachment_bytes
                ):
                    try:
                        data = await client.download_media(msg, file=bytes)
                    except Exception as exc:
                        logger.warning(
                            "download attachment failed msg=%s: %s", msg.id, exc
                        )
                        data = None
                    if data and isinstance(data, bytes) and len(data) <= max_attachment_bytes:
                        attachments.append(
                            {
                                "filename": fname or f"file.{ext}",
                                "mime_type": mime,
                                "file_type": ext,
                                "size": len(data),
                                "bytes": data,
                            }
                        )
                elif ext and ext in allowed_extensions and size > max_attachment_bytes:
                    logger.info(
                        "skip attachment: too large msg=%s size=%s", msg.id, size
                    )

            out.append(
                {
                    "telegram_message_id": int(msg.id),
                    "published_at": published,
                    "author_id": author_id,
                    "author_name": author_name,
                    "text": text,
                    "message_link": link,
                    "attachments": attachments,
                }
            )
    finally:
        await client.disconnect()
    return out
