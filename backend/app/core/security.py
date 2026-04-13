from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password[:72])


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain[:72], hashed)


def _exp_unix(expire: datetime) -> int:
    return int(expire.timestamp())


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "exp": _exp_unix(expire),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID, jti: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": str(user_id),
        "type": "refresh",
        "jti": jti,
        "exp": _exp_unix(expire),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])


def decode_token_optional(token: str) -> dict | None:
    try:
        return decode_token(token)
    except JWTError:
        return None


def create_oauth_state(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=10)
    payload = {
        "sub": str(user_id),
        "typ": "hh_oauth_state",
        "exp": _exp_unix(expire),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_oauth_state(state: str, user_id: uuid.UUID) -> bool:
    try:
        data = jwt.decode(state, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return False
    if data.get("typ") != "hh_oauth_state":
        return False
    return data.get("sub") == str(user_id)


def decode_hh_oauth_user_id(state: str) -> uuid.UUID | None:
    """Извлекает user_id из state OAuth (без проверки совпадения с текущей сессией)."""
    if not (state and state.strip()):
        return None
    try:
        data = jwt.decode(state.strip(), settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if data.get("typ") != "hh_oauth_state":
        return None
    sub = data.get("sub")
    if not sub:
        return None
    try:
        return uuid.UUID(str(sub))
    except ValueError:
        return None


SOCIAL_OAUTH_STATE_TYP = "social_oauth_state"
SOCIAL_OAUTH_STATE_EXPIRE_MINUTES = 10


def create_social_oauth_state(provider: str, *, code_verifier: str | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=SOCIAL_OAUTH_STATE_EXPIRE_MINUTES)
    payload: dict = {
        "typ": SOCIAL_OAUTH_STATE_TYP,
        "jti": str(uuid.uuid4()),
        "prov": provider,
        "exp": _exp_unix(expire),
    }
    if code_verifier:
        payload["cv"] = code_verifier
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def verify_social_oauth_state(state: str, *, expected_provider: str) -> dict | None:
    if not (state and str(state).strip()):
        return None
    try:
        data = jwt.decode(
            str(state).strip(),
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None
    if data.get("typ") != SOCIAL_OAUTH_STATE_TYP:
        return None
    if data.get("prov") != expected_provider:
        return None
    return data


def generate_pkce_pair() -> tuple[str, str]:
    """Возвращает (code_verifier, code_challenge S256) для VK ID."""
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).decode("ascii").rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


def hash_handoff_code(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def generate_handoff_plain() -> str:
    return secrets.token_urlsafe(32)
