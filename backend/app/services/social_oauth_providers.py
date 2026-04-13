from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

USER_AGENT = "HR-Service/1.0"


@dataclass(frozen=True)
class SocialProfile:
    provider_user_id: str
    email: str | None


class SocialOAuthProviderError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


YANDEX_AUTH_URL = "https://oauth.yandex.ru/authorize"
YANDEX_TOKEN_URL = "https://oauth.yandex.ru/token"
YANDEX_INFO_URL = "https://login.yandex.ru/info"


def _mock_profile(provider: str, code: str) -> SocialProfile:
    """Детерминированный профиль для тестов; fixture_email:addr@test — заданный email."""
    c = (code or "").strip()
    if c.startswith("fixture_email:"):
        email = c[len("fixture_email:") :].strip().lower()
        if email:
            digest = hashlib.sha256(f"{provider}:{email}".encode()).hexdigest()[:20]
            return SocialProfile(provider_user_id=f"mock_{provider}_{digest}", email=email)
    digest = hashlib.sha256(f"{provider}:{c}".encode()).hexdigest()[:24]
    return SocialProfile(
        provider_user_id=f"{provider}_{digest}",
        email=f"{provider}_{digest}@oauth.mock",
    )


def build_yandex_authorize_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.yandex_client_id,
        "redirect_uri": settings.yandex_redirect_uri,
        "state": state,
        "scope": "login:email login:info",
    }
    return f"{YANDEX_AUTH_URL}?{urlencode(params)}"


async def yandex_exchange_and_profile(code: str) -> SocialProfile:
    if settings.feature_use_mock_social_oauth:
        return _mock_profile("yandex", code)

    if not settings.yandex_client_id or not settings.yandex_client_secret:
        raise SocialOAuthProviderError(503, "Yandex OAuth is not configured")

    async with httpx.AsyncClient() as client:
        tr = await client.post(
            YANDEX_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.yandex_client_id,
                "client_secret": settings.yandex_client_secret,
                "redirect_uri": settings.yandex_redirect_uri,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        if not tr.is_success:
            raise SocialOAuthProviderError(
                tr.status_code if tr.status_code < 500 else 502,
                "Yandex token exchange failed",
            )
        tokens: dict[str, Any] = tr.json()
        access = tokens.get("access_token")
        if not access:
            raise SocialOAuthProviderError(400, "Invalid Yandex authorization code")

        ir = await client.get(
            YANDEX_INFO_URL,
            headers={
                "Authorization": f"OAuth {access}",
                "User-Agent": USER_AGENT,
            },
            timeout=30.0,
        )
        if not ir.is_success:
            raise SocialOAuthProviderError(502, "Yandex user info failed")
        info = ir.json()

    uid = str(info.get("id") or info.get("client_id") or "").strip()
    email = None
    if isinstance(info.get("default_email"), str) and info["default_email"].strip():
        email = info["default_email"].strip().lower()
    elif isinstance(info.get("emails"), list) and info["emails"]:
        first = info["emails"][0]
        if isinstance(first, str) and first.strip():
            email = first.strip().lower()

    if not uid:
        raise SocialOAuthProviderError(502, "Yandex profile has no user id")

    return SocialProfile(provider_user_id=uid, email=email)


def _vk_base() -> str:
    return settings.vk_oauth_base_url.rstrip("/")


def build_vk_authorize_url(state: str, *, code_challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.vk_client_id,
        "redirect_uri": settings.vk_redirect_uri,
        "state": state,
        "scope": "vkid.personal_info email",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{_vk_base()}/authorize?{urlencode(params)}"


async def vk_exchange_and_profile(code: str, *, code_verifier: str) -> SocialProfile:
    if settings.feature_use_mock_social_oauth:
        return _mock_profile("vk", code)

    if not settings.vk_client_id or not settings.vk_client_secret:
        raise SocialOAuthProviderError(503, "VK OAuth is not configured")

    token_url = f"{_vk_base()}/oauth2/auth"
    async with httpx.AsyncClient() as client:
        tr = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.vk_redirect_uri,
                "client_id": settings.vk_client_id,
                "client_secret": settings.vk_client_secret,
                "code_verifier": code_verifier,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        if not tr.is_success:
            raise SocialOAuthProviderError(
                tr.status_code if tr.status_code < 500 else 502,
                "VK token exchange failed",
            )
        tokens: dict[str, Any] = tr.json()
        access = tokens.get("access_token")
        if not access:
            raise SocialOAuthProviderError(400, "Invalid VK authorization code")

        user_id = tokens.get("user_id")
        uid = str(user_id).strip() if user_id is not None else ""

        ur = await client.get(
            f"{_vk_base()}/oauth2/user_info",
            headers={
                "Authorization": f"Bearer {access}",
                "User-Agent": USER_AGENT,
            },
            timeout=30.0,
        )
        if not ur.is_success:
            if uid:
                return SocialProfile(provider_user_id=uid, email=None)
            raise SocialOAuthProviderError(502, "VK user info failed")

        raw = ur.text
        try:
            info = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            info = {}
        if not isinstance(info, dict):
            info = {}

        if not uid:
            u = info.get("user") if isinstance(info.get("user"), dict) else info
            if isinstance(u, dict):
                for key in ("user_id", "id", "sub"):
                    if u.get(key) is not None:
                        uid = str(u[key]).strip()
                        break
            if not uid and info.get("user_id") is not None:
                uid = str(info["user_id"]).strip()

        email = None
        u = info.get("user") if isinstance(info.get("user"), dict) else info
        if isinstance(u, dict):
            e = u.get("email")
            if isinstance(e, str) and e.strip():
                email = e.strip().lower()

        if not uid:
            raise SocialOAuthProviderError(502, "VK profile has no user id")

    return SocialProfile(provider_user_id=uid, email=email)
