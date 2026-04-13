from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import settings
from app.models.user import User
from app.core.security import (
    create_social_oauth_state,
    generate_pkce_pair,
    verify_social_oauth_state,
)
from app.schemas.auth import OAuthExchangeIn, TokenOut
from app.services.auth_tokens import issue_token_out
from app.services import oauth_handoff
from app.services.social_oauth_account import resolve_user_for_social_login
from app.services.social_oauth_providers import (
    SocialOAuthProviderError,
    build_vk_authorize_url,
    build_yandex_authorize_url,
    vk_exchange_and_profile,
    yandex_exchange_and_profile,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_SOCIAL_PROVIDERS = frozenset({"yandex", "vk"})


def _frontend_base() -> str:
    base = (settings.hr_public_base_url or "").strip()
    if base:
        return base.rstrip("/")
    if settings.cors_origin_list:
        return settings.cors_origin_list[0].rstrip("/")
    return "http://localhost:3000"


def _redirect_finish(**params: str) -> RedirectResponse:
    url = f"{_frontend_base()}/auth/oauth/finish?{urlencode(params)}"
    return RedirectResponse(url, status_code=302)


def _redirect_finish_handoff(plain_code: str) -> RedirectResponse:
    """Код handoff в fragment (#), чтобы не попадал в query-логи прокси."""
    frag = urlencode({"code": plain_code})
    url = f"{_frontend_base()}/auth/oauth/finish#{frag}"
    return RedirectResponse(url, status_code=302)


def _provider_configured(provider: str) -> bool:
    if settings.feature_use_mock_social_oauth:
        return True
    if provider == "yandex":
        return bool(
            settings.yandex_client_id.strip()
            and settings.yandex_client_secret.strip()
            and settings.yandex_redirect_uri.strip()
        )
    if provider == "vk":
        return bool(
            settings.vk_client_id.strip()
            and settings.vk_client_secret.strip()
            and settings.vk_redirect_uri.strip()
        )
    return False


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str) -> RedirectResponse:
    p = provider.lower().strip()
    if p not in _SOCIAL_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")
    if not _provider_configured(p):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OAuth provider is not configured",
        )

    if p == "vk":
        verifier, challenge = generate_pkce_pair()
        state = create_social_oauth_state("vk", code_verifier=verifier)
        url = build_vk_authorize_url(state, code_challenge=challenge)
    else:
        state = create_social_oauth_state("yandex")
        url = build_yandex_authorize_url(state)

    return RedirectResponse(url, status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    db: Session = Depends(get_db),
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> RedirectResponse:
    p = provider.lower().strip()
    if p not in _SOCIAL_PROVIDERS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown provider")

    if error:
        msg = (error_description or error or "access_denied")[:200]
        return _redirect_finish(oauth_error=error, oauth_error_description=msg)

    if not code or not str(code).strip() or not state or not str(state).strip():
        return _redirect_finish(oauth_error="invalid_request", oauth_error_description="missing_code")

    st = verify_social_oauth_state(str(state).strip(), expected_provider=p)
    if not st:
        return _redirect_finish(oauth_error="invalid_state", oauth_error_description="invalid_state")

    code_verifier = st.get("cv")
    if p == "vk":
        if not isinstance(code_verifier, str) or not code_verifier.strip():
            return _redirect_finish(
                oauth_error="invalid_state",
                oauth_error_description="missing_pkce",
            )
        try:
            profile = await vk_exchange_and_profile(
                str(code).strip(),
                code_verifier=str(code_verifier).strip(),
            )
        except SocialOAuthProviderError as exc:
            return _redirect_finish(
                oauth_error="token_exchange",
                oauth_error_description=exc.detail[:200],
            )
    else:
        try:
            profile = await yandex_exchange_and_profile(str(code).strip())
        except SocialOAuthProviderError as exc:
            return _redirect_finish(
                oauth_error="token_exchange",
                oauth_error_description=exc.detail[:200],
            )

    try:
        user = resolve_user_for_social_login(
            db,
            provider=p,
            provider_user_id=profile.provider_user_id,
            email=profile.email,
        )
    except ValueError:
        return _redirect_finish(
            oauth_error="profile",
            oauth_error_description="invalid_profile",
        )

    handoff_plain = oauth_handoff.issue_handoff_code(db, user.id)
    return _redirect_finish_handoff(handoff_plain)


@router.post("/oauth/exchange", response_model=TokenOut)
def oauth_exchange(body: OAuthExchangeIn, db: Session = Depends(get_db)) -> TokenOut:
    uid = oauth_handoff.consume_handoff_code(db, body.code)
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OAuth handoff code",
        )
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OAuth handoff code",
        )
    return issue_token_out(db, user)
