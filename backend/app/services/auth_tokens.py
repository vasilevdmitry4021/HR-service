from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.models.user import User
from app.schemas.auth import TokenOut


def issue_token_out(db: Session, user: User) -> TokenOut:
    jti = str(uuid4())
    user.active_refresh_jti = jti
    db.commit()
    db.refresh(user)
    return TokenOut(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id, jti),
        expires_in=settings.access_token_expire_minutes * 60,
    )
