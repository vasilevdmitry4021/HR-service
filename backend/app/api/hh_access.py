"""Доступ к OAuth-токену HeadHunter пользователя: чтение и при необходимости refresh."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.hh import resolve_hh_application_oauth
from app.config import settings
from app.models.api_key import ApiKey
from app.services import encryption
from app.services.hh_client import HHClientError, refresh_access_token

_REFRESH_SKEW = timedelta(seconds=120)


def _parse_expires_at(raw: object) -> datetime | None:
    if raw is None:
        return None
    try:
        s = str(raw).strip()
        if not s:
            return None
        exp = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp
    except (TypeError, ValueError):
        return None


async def ensure_hh_access_token(
    db: Session,
    user_id: uuid.UUID,
    *,
    force_refresh: bool = False,
) -> str | None:
    """
    Возвращает действующий access_token, при истечении срока — обновление через refresh_token
    и запись в ApiKey.
    """
    row = db.scalars(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.created_at.desc())
    ).first()
    if not row:
        return None
    try:
        data = encryption.decrypt_json(row.encrypted_key)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    access = data.get("access_token")
    refresh = data.get("refresh_token")
    access_str = str(access).strip() if access else ""

    if settings.feature_use_mock_hh:
        return access_str or None

    exp = _parse_expires_at(data.get("expires_at"))
    now = datetime.now(timezone.utc)
    if exp is not None:
        expired_or_soon = now + _REFRESH_SKEW >= exp
    else:
        expired_or_soon = True
    need_refresh = force_refresh or expired_or_soon

    if not need_refresh:
        return access_str or None

    fallback_access = None if force_refresh else (access_str or None)
    if not refresh or not str(refresh).strip():
        return fallback_access

    triple = resolve_hh_application_oauth(db)
    if triple:
        client_id, client_secret, _rid = triple
    else:
        client_id = settings.hh_client_id
        client_secret = settings.hh_client_secret
    if not str(client_id or "").strip() or not str(client_secret or "").strip():
        return fallback_access

    try:
        tokens = await refresh_access_token(
            str(refresh).strip(),
            client_id=str(client_id).strip(),
            client_secret=str(client_secret).strip(),
        )
    except HHClientError:
        return fallback_access

    new_access = tokens.get("access_token")
    if not new_access:
        return fallback_access

    new_refresh = tokens.get("refresh_token") or refresh
    expires_in = int(tokens.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    payload = {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "expires_at": expires_at.isoformat(),
        "hh_user_id": str(data.get("hh_user_id") or ""),
        "employer_name": str(data.get("employer_name") or ""),
    }
    row.encrypted_key = encryption.encrypt_json(payload)
    db.commit()
    return str(new_access)
