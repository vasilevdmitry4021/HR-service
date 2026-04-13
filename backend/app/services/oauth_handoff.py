from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.security import generate_handoff_plain, hash_handoff_code
from app.models.oauth_handoff import OAuthHandoffCode

HANDOFF_TTL_SECONDS = 120


def issue_handoff_code(db: Session, user_id: uuid.UUID) -> str:
    plain = generate_handoff_plain()
    now = datetime.now(timezone.utc)
    row = OAuthHandoffCode(
        code_hash=hash_handoff_code(plain),
        user_id=user_id,
        expires_at=now + timedelta(seconds=HANDOFF_TTL_SECONDS),
    )
    db.add(row)
    db.commit()
    return plain


def consume_handoff_code(db: Session, plain: str) -> uuid.UUID | None:
    if not plain or not plain.strip():
        return None
    h = hash_handoff_code(plain.strip())
    now = datetime.now(timezone.utc)
    row = (
        db.query(OAuthHandoffCode)
        .filter(
            OAuthHandoffCode.code_hash == h,
            OAuthHandoffCode.used_at.is_(None),
            OAuthHandoffCode.expires_at > now,
        )
        .one_or_none()
    )
    if row is None:
        return None
    row.used_at = now
    db.commit()
    return row.user_id
