"""Асинхронная авторизация Telethon (отправка кода, ввод кода)."""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)


class InvalidTwoFactorPasswordError(Exception):
    """Telegram отклонил облачный пароль (двухэтапная проверка)."""


SignInWithCodeStatus = Literal["authorized", "need_password"]


def phone_hint_mask(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    if len(d) <= 4:
        return "****"
    return f"…{d[-4:]}"


async def send_code_request(
    api_id: int,
    api_hash: str,
    phone: str,
    session_string: str | None,
) -> tuple[str, str]:
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    sess = StringSession(session_string or "")
    client = TelegramClient(sess, api_id, api_hash)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        h = getattr(sent, "phone_code_hash", None)
        if not isinstance(h, str) or not h.strip():
            raise RuntimeError("Telegram не вернул phone_code_hash")
        new_session = client.session.save()
        return new_session, h.strip()
    finally:
        await client.disconnect()


async def sign_in_with_code(
    api_id: int,
    api_hash: str,
    session_string: str,
    phone: str,
    code: str,
    phone_code_hash: str,
) -> tuple[str, SignInWithCodeStatus]:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.connect()
    try:
        try:
            await client.sign_in(
                phone=phone,
                code=code.strip(),
                phone_code_hash=phone_code_hash,
            )
        except SessionPasswordNeededError:
            return client.session.save(), "need_password"
        return client.session.save(), "authorized"
    finally:
        await client.disconnect()


async def sign_in_with_password(
    api_id: int,
    api_hash: str,
    session_string: str,
    password: str,
) -> str:
    from telethon import TelegramClient
    from telethon.errors import PasswordHashInvalidError
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.connect()
    try:
        try:
            await client.sign_in(password=password.strip())
        except PasswordHashInvalidError as e:
            raise InvalidTwoFactorPasswordError from e
        return client.session.save()
    finally:
        await client.disconnect()


def telethon_import_error() -> BaseException | None:
    try:
        import telethon  # noqa: F401
    except ImportError as e:
        return e
    return None
