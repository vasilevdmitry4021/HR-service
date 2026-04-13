from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.config import settings
from app.models.oauth_identity import OAuthIdentity
from app.models.user import User


def resolve_user_for_social_login(
    db: Session,
    *,
    provider: str,
    provider_user_id: str,
    email: str | None,
) -> User:
    """Находит или создаёт пользователя по связке провайдера и при необходимости по email."""
    pid = (provider_user_id or "").strip()
    if not pid:
        raise ValueError("empty provider_user_id")

    existing_oid = (
        db.query(OAuthIdentity)
        .filter(
            OAuthIdentity.provider == provider,
            OAuthIdentity.provider_user_id == pid,
        )
        .one_or_none()
    )
    if existing_oid:
        user = db.get(User, existing_oid.user_id)
        if user:
            return user

    email_norm = (email or "").strip().lower()
    if not email_norm:
        email_norm = f"{provider}_{pid}@users.internal"

    user_by_email = db.query(User).filter(User.email == email_norm).one_or_none()
    if (
        user_by_email
        and settings.social_oauth_strict_email_link
        and user_by_email.password_hash is not None
    ):
        user_by_email = None
        email_norm = f"{provider}_{pid}@users.internal"
        user_by_email = db.query(User).filter(User.email == email_norm).one_or_none()

    if user_by_email:
        db.add(
            OAuthIdentity(
                user_id=user_by_email.id,
                provider=provider,
                provider_user_id=pid,
            )
        )
        db.commit()
        db.refresh(user_by_email)
        return user_by_email

    user = User(email=email_norm, password_hash=None)
    db.add(user)
    db.flush()
    db.add(
        OAuthIdentity(
            user_id=user.id,
            provider=provider,
            provider_user_id=pid,
        )
    )
    db.commit()
    db.refresh(user)
    return user
