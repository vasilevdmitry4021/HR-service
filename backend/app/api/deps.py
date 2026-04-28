from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decode_token_optional
from app.db.session import get_db
from app.models.user import User

security = HTTPBearer()


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> uuid.UUID:
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme",
        )
    payload = decode_token_optional(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject",
        ) from None


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    try:
        request.state.user_id = user.id
        request.state.user_email = user.email
    except Exception:
        pass
    return user


def _settings_admin_email_allowlist() -> set[str]:
    return {
        e.strip().casefold()
        for e in (settings.settings_admin_emails or "").split(",")
        if e.strip()
    }


def _settings_admin_user_id_allowlist() -> set[str]:
    return {
        i.strip().lower()
        for i in (settings.settings_admin_user_ids or "").split(",")
        if i.strip()
    }


def is_settings_admin_user(user: User) -> bool:
    """Те же критерии «администратор настроек», что и для записи интеграций (без проверки feature_settings_write)."""
    if user.is_super_admin:
        return True
    if user.is_admin:
        return True
    if user.can_edit_integration_settings:
        return True
    if user.email.casefold() in _settings_admin_email_allowlist():
        return True
    if str(user.id).lower() in _settings_admin_user_id_allowlist():
        return True
    return False


def can_write_integration_settings(user: User) -> bool:
    """Может ли пользователь сохранять глобальные настройки интеграций (для UI / GET /me)."""
    if not settings.feature_settings_write:
        return False
    if not settings.settings_admin_only:
        return True
    return is_settings_admin_user(user)


def is_super_settings_admin(user: User) -> bool:
    """
    Суперпользователь для отзыва доступа к глобальным настройкам (DELETE списка редакторов).
    Права задаются только флагом users.is_super_admin в БД.
    """
    return bool(user.is_super_admin)


def can_manage_integration_editors(user: User) -> bool:
    """
    Управление списком редакторов интеграций (API / UI): is_admin или allowlist в .env.
    Назначенные редакторы (can_edit_integration_settings без остального) сюда не входят.
    """
    if user.is_super_admin:
        return True
    if user.is_admin:
        return True
    if user.email.casefold() in _settings_admin_email_allowlist():
        return True
    if str(user.id).lower() in _settings_admin_user_id_allowlist():
        return True
    return False


def get_system_admin(user: User = Depends(get_current_user)) -> User:
    """Только полный администратор системы (is_admin в БД). Список редакторов см. get_integration_editors_manager."""
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступно только администратору системы",
        )
    return user


def get_integration_editors_manager(user: User = Depends(get_current_user)) -> User:
    if not can_manage_integration_editors(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав для управления списком редакторов настроек интеграций",
        )
    return user


def get_super_settings_admin(user: User = Depends(get_current_user)) -> User:
    """Только суперпользователь (users.is_super_admin=true) может отзывать права через DELETE."""
    if not is_super_settings_admin(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Отзыв прав редактора глобальных настроек доступен только суперпользователю",
        )
    return user


def get_settings_admin(user: User = Depends(get_current_user)) -> User:
    """
    Доступ к записи глобальных интеграций (HH-приложение, e-staff, LLM в system_settings).
    """
    if not settings.feature_settings_write:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Запись глобальных настроек через API отключена",
        )
    if not settings.settings_admin_only:
        return user
    if is_settings_admin_user(user):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Недостаточно прав для изменения глобальных настроек интеграций",
    )


def require_search_parse_debug_access(user: User = Depends(get_current_user)) -> User:
    """Доступ к отладочному разбору поиска: флаг и (при settings_admin_only) те же права, что у админа настроек."""
    if not settings.feature_search_parse_debug:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Эндпоинт отключён",
        )
    if not settings.settings_admin_only:
        return user
    if is_settings_admin_user(user):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Недостаточно прав для отладочного разбора запроса",
    )
