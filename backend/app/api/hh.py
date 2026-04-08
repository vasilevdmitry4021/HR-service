from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.core.security import create_oauth_state, decode_hh_oauth_user_id, verify_oauth_state
from app.models.api_key import ApiKey
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.hh import (
    HHConnectCallbackIn,
    HHConnectOut,
    HHConnectSuccessOut,
    HHCredentialsIn,
    HHCredentialsPutOut,
    HHCredentialsStatusOut,
    HHStatusOut,
)
from app.services import encryption, hh_client
from app.services.hh_client import HHClientError

router = APIRouter(prefix="/hh", tags=["hh"])


def resolve_hh_application_oauth(db: Session) -> tuple[str, str, str] | None:
    """Эффективные client_id, client_secret и redirect_uri (БД и переменные окружения)."""
    from app.config import get_hh_oauth_payload_from_db

    payload = get_hh_oauth_payload_from_db(db)
    cid_src = (payload.get("client_id") if payload else None) or settings.hh_client_id
    sec_src = (payload.get("client_secret") if payload else None) or settings.hh_client_secret
    rid_src = (payload.get("redirect_uri") if payload else None) or settings.hh_redirect_uri
    cid = str(cid_src or "").strip()
    sec = str(sec_src or "").strip()
    rid = str(rid_src or "").strip()
    if not rid:
        rid = str(settings.hh_redirect_uri or "").strip()
    if cid and sec and rid:
        return cid, sec, rid
    return None


def _append_query(url: str, params: dict[str, str]) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urlencode(params)}"


def _frontend_settings_redirect(query: dict[str, str]) -> RedirectResponse:
    base = (
        settings.cors_origin_list[0]
        if settings.cors_origin_list
        else "http://localhost:3000"
    )
    url = f"{base.rstrip('/')}/settings?{urlencode(query)}"
    return RedirectResponse(url, status_code=302)


async def _complete_hh_oauth(
    db: Session,
    user: User,
    code: str,
    state: str | None,
) -> HHConnectSuccessOut:
    if not state or not str(state).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )
    if not verify_oauth_state(state.strip(), user.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OAuth state",
        )
    triple = resolve_hh_application_oauth(db)
    if not settings.feature_use_mock_hh and not triple:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HeadHunter OAuth is not configured",
        )
    try:
        if settings.feature_use_mock_hh:
            tokens = await hh_client.exchange_code_for_tokens(code)
        else:
            assert triple is not None
            cid, sec, rid = triple
            tokens = await hh_client.exchange_code_for_tokens(
                code,
                client_id=cid,
                client_secret=sec,
                redirect_uri=rid,
            )
    except HHClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="HeadHunter token exchange failed",
        ) from exc

    access = tokens.get("access_token")
    if not access:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid authorization code",
        )

    refresh = tokens.get("refresh_token")
    expires_in = int(tokens.get("expires_in") or 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    hh_user_id = str(tokens.get("hh_user_id") or tokens.get("id") or "")
    employer_name = str(tokens.get("employer_name") or "")

    payload = {
        "access_token": access,
        "refresh_token": refresh,
        "expires_at": expires_at.isoformat(),
        "hh_user_id": hh_user_id,
        "employer_name": employer_name,
    }
    blob = encryption.encrypt_json(payload)

    for row in db.scalars(select(ApiKey).where(ApiKey.user_id == user.id)):
        db.delete(row)

    db.add(ApiKey(user_id=user.id, encrypted_key=blob, is_valid=True))
    db.commit()

    return HHConnectSuccessOut(
        hh_user_id=hh_user_id or "unknown",
        expires_at=expires_at,
    )


@router.get("/callback")
async def hh_oauth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Браузерный redirect от HeadHunter (redirect_uri на бэкенд)."""
    if error:
        msg = error_description or error
        return _frontend_settings_redirect({"hh_oauth": "error", "hh_msg": msg})
    if not code or not state:
        return _frontend_settings_redirect(
            {"hh_oauth": "error", "hh_msg": "Отсутствует код или state авторизации"},
        )

    user_id = decode_hh_oauth_user_id(state)
    if not user_id:
        return _frontend_settings_redirect(
            {"hh_oauth": "error", "hh_msg": "Недействительный параметр state"},
        )

    user = db.get(User, user_id)
    if not user:
        return _frontend_settings_redirect(
            {"hh_oauth": "error", "hh_msg": "Пользователь не найден"},
        )

    try:
        await _complete_hh_oauth(db, user, code, state)
    except HTTPException as exc:
        detail = exc.detail
        text = detail if isinstance(detail, str) else str(detail)
        return _frontend_settings_redirect({"hh_oauth": "error", "hh_msg": text})
    return _frontend_settings_redirect({"hh_oauth": "ok"})


@router.get("/connect", response_model=HHConnectOut)
def hh_connect_start(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HHConnectOut:
    state = create_oauth_state(user.id)
    triple = resolve_hh_application_oauth(db)
    if settings.feature_use_mock_hh:
        rid = triple[2] if triple else settings.hh_redirect_uri
        authorization_url = _append_query(
            rid,
            {"code": "mock_authorization_code", "state": state},
        )
        return HHConnectOut(authorization_url=authorization_url)
    if not triple:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HeadHunter OAuth is not configured",
        )
    cid, _sec, rid = triple
    authorization_url = hh_client.build_authorization_url(
        state, client_id=cid, redirect_uri=rid
    )
    return HHConnectOut(authorization_url=authorization_url)


@router.post("/connect", response_model=HHConnectSuccessOut)
async def hh_connect_callback(
    body: HHConnectCallbackIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> HHConnectSuccessOut:
    return await _complete_hh_oauth(db, user, body.code, body.state)


@router.get("/status", response_model=HHStatusOut)
async def hh_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> HHStatusOut:
    row = db.scalars(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    ).first()
    if not row:
        return HHStatusOut(
            connected=False,
            message="HeadHunter authorization required",
        )
    try:
        data = encryption.decrypt_json(row.encrypted_key)
    except Exception:
        return HHStatusOut(connected=False, message="Stored tokens are unreadable")

    access = data.get("access_token")
    exp_raw = data.get("expires_at")
    exp: datetime | None = None
    if isinstance(exp_raw, str):
        exp = datetime.fromisoformat(exp_raw.replace("Z", "+00:00"))

    services = None
    employer_name = data.get("employer_name")
    hh_user_id = data.get("hh_user_id")

    if access and not settings.feature_use_mock_hh:
        try:
            me = await hh_client.fetch_employer_me(access)
            hh_user_id = str(me.get("id", hh_user_id))
            employer_name = me.get("name") or employer_name
            services = me.get("services") or {"resume_database": True, "contacts_available": 0}
            row.last_checked_at = datetime.now(timezone.utc)
            row.is_valid = True
            db.commit()
        except HHClientError:
            row.is_valid = False
            db.commit()
        except Exception:
            row.is_valid = False
            db.commit()

    if settings.feature_use_mock_hh:
        services = {"resume_database": True, "contacts_available": 150}

    return HHStatusOut(
        connected=True,
        hh_user_id=hh_user_id,
        employer_name=employer_name,
        access_expires_at=exp,
        services=services,
    )


@router.get("/credentials", response_model=HHCredentialsStatusOut)
def get_hh_credentials_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> HHCredentialsStatusOut:
    from app.config import get_hh_credentials_from_db, get_hh_oauth_payload_from_db

    payload = get_hh_oauth_payload_from_db(db)
    configured = get_hh_credentials_from_db(db) is not None
    redirect_uri = settings.hh_redirect_uri
    ru = payload.get("redirect_uri") if payload else None
    if isinstance(ru, str) and ru.strip():
        redirect_uri = ru.strip()
    return HHCredentialsStatusOut(configured=configured, redirect_uri=redirect_uri)


@router.put("/credentials", response_model=HHCredentialsPutOut)
def update_hh_credentials(
    body: HHCredentialsIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> HHCredentialsPutOut:
    from datetime import datetime, timezone

    payload = {
        "client_id": body.client_id,
        "client_secret": body.client_secret,
        "redirect_uri": body.redirect_uri or settings.hh_redirect_uri,
    }
    blob = encryption.encrypt_json(payload)

    row = db.scalars(
        select(SystemSettings).where(SystemSettings.key == "hh_credentials")
    ).first()

    if row:
        row.encrypted_value = blob
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(SystemSettings(key="hh_credentials", encrypted_value=blob))

    db.commit()
    return HHCredentialsPutOut()
