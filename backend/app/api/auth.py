from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    can_manage_integration_editors,
    can_write_integration_settings,
    get_current_user,
    get_db,
    is_super_settings_admin,
)
from app.core.security import decode_token_optional, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import LoginIn, RefreshIn, RegisterIn, RegisterOut, TokenOut, UserMeOut
from app.services.auth_tokens import issue_token_out

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> User:
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        ) from None
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    user = db.query(User).filter(User.email == body.email.lower()).one_or_none()
    if (
        not user
        or user.password_hash is None
        or not verify_password(body.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    return issue_token_out(db, user)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    payload = decode_token_optional(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    try:
        uid = UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        ) from None
    user = db.get(User, uid)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    token_jti = payload.get("jti")
    stored = user.active_refresh_jti
    if stored is not None:
        if not token_jti or str(token_jti) != str(stored):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token",
            )
    elif token_jti is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    return issue_token_out(db, user)


@router.get("/me", response_model=UserMeOut)
def me(user: User = Depends(get_current_user)) -> UserMeOut:
    return UserMeOut(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        is_super_admin=user.is_super_admin,
        can_write_integration_settings=can_write_integration_settings(user),
        can_manage_integration_editors=can_manage_integration_editors(user),
        can_revoke_integration_editor_access=is_super_settings_admin(user),
    )
