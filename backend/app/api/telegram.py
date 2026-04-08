from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.config import settings
from app.models.telegram_models import (
    TelegramAccount,
    TelegramSource,
    TelegramSyncRun,
)
from app.models.user import User
from app.schemas.telegram import (
    TelegramConnectIn,
    TelegramConnectOut,
    TelegramSourceIn,
    TelegramSourceOut,
    TelegramSourcePatchIn,
    TelegramStatusOut,
    TelegramSyncRunOut,
    TelegramVerifyIn,
    TelegramVerifyPasswordIn,
    TelegramVerifyOut,
)
from app.services import encryption
from app.services.telegram_connect import (
    InvalidTwoFactorPasswordError,
    phone_hint_mask,
    send_code_request,
    sign_in_with_code,
    sign_in_with_password,
    telethon_import_error,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])

AUTH_PENDING = "pending"
AUTH_AUTHORIZED = "authorized"
AUTH_EXPIRED = "expired"
AUTH_ERROR = "error"

PENDING_STAGE_2FA = "2fa_password"


def _tg_feature() -> None:
    if not settings.feature_use_telegram_source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Интеграция Telegram отключена",
        )


def _user_account(db: Session, user_id: uuid.UUID) -> TelegramAccount | None:
    return db.scalars(
        select(TelegramAccount)
        .where(TelegramAccount.owner_id == user_id)
        .order_by(TelegramAccount.updated_at.desc())
    ).first()


def _normalize_telegram_link(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    low = s.lower()
    if low.startswith("http://") or low.startswith("https://"):
        if re.match(r"https?://(t(elegram)?\.me)(/|$)", s, re.I):
            return s
        return None
    if s.startswith("@"):
        return s
    if re.match(r"^[A-Za-z][A-Za-z0-9_]{3,31}$", s):
        return f"https://t.me/{s}"
    if re.match(r"^t\.me/", low) or re.match(r"^telegram\.me/", low):
        return f"https://{s}"
    if s.startswith("+"):
        return f"https://t.me/{s}"
    if low.startswith("joinchat/"):
        return f"https://t.me/{s}"
    if low.startswith("tg://"):
        return s
    return None


def _map_telegram_access_error(exc: BaseException) -> tuple[str, str]:
    from telethon.errors import (
        ChannelPrivateError,
        ChatAdminRequiredError,
        FloodWaitError,
        InviteHashExpiredError,
        InviteHashInvalidError,
        UsernameInvalidError,
        UsernameNotOccupiedError,
        UserNotParticipantError,
    )

    msg = (str(exc).strip() or type(exc).__name__)[:500]
    if isinstance(
        exc,
        (UsernameNotOccupiedError, UsernameInvalidError, InviteHashInvalidError),
    ):
        return "invalid", msg
    if isinstance(
        exc,
        (
            ChannelPrivateError,
            UserNotParticipantError,
            ChatAdminRequiredError,
            InviteHashExpiredError,
        ),
    ):
        return "access_required", msg
    if isinstance(exc, FloodWaitError):
        return "unavailable", f"Лимит Telegram, повторите через {exc.seconds} с"
    return "unavailable", msg


async def _probe_telegram_source(
    api_id: int,
    api_hash: str,
    session_str: str,
    normalized_link: str,
) -> tuple[int, str, str, str, str | None]:
    """Вернуть peer id, тип, отображаемое имя, статус доступа и текст ошибки."""
    from telethon import TelegramClient, utils
    from telethon.sessions import StringSession
    from telethon.tl.types import Channel, Chat, User

    client = TelegramClient(StringSession(session_str or ""), api_id, api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return (
                0,
                "channel",
                normalized_link[:200],
                "access_required",
                "Сессия Telegram не авторизована",
            )
        try:
            entity = await client.get_entity(normalized_link)
        except Exception as exc:
            st, em = _map_telegram_access_error(exc)
            return 0, "channel", "", st, em
        if isinstance(entity, User):
            return (
                0,
                "channel",
                "",
                "invalid",
                "Укажите канал, группу или чат, а не профиль пользователя",
            )
        if isinstance(entity, Chat):
            src_type = "chat"
        elif isinstance(entity, Channel):
            src_type = "channel" if entity.broadcast else "group"
        else:
            src_type = "channel"
        tid = int(utils.get_peer_id(entity))
        title = getattr(entity, "title", None) or ""
        un = getattr(entity, "username", None) or ""
        display = (
            title.strip() or (f"@{un}" if un else "") or normalized_link
        )[:512]
        return tid, src_type, display, "active", None
    finally:
        await client.disconnect()


def _telegram_source_to_out(row: TelegramSource) -> TelegramSourceOut:
    return TelegramSourceOut(
        id=str(row.id),
        account_id=str(row.account_id),
        telegram_id=int(row.telegram_id),
        link=row.link,
        type=row.type,
        display_name=row.display_name,
        access_status=row.access_status,
        is_enabled=row.is_enabled,
        last_message_id=int(row.last_message_id) if row.last_message_id else None,
        last_check_at=row.last_check_at,
        last_sync_at=row.last_sync_at,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/status", response_model=TelegramStatusOut)
def telegram_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramStatusOut:
    if not settings.feature_use_telegram_source:
        return TelegramStatusOut(feature_enabled=False, connected=False)
    acc = _user_account(db, user.id)
    if not acc:
        return TelegramStatusOut(feature_enabled=True, connected=False)
    ok = acc.auth_status == AUTH_AUTHORIZED
    pend = acc.pending_auth if isinstance(acc.pending_auth, dict) else {}
    awaiting_2fa = (
        acc.auth_status == AUTH_PENDING and pend.get("stage") == PENDING_STAGE_2FA
    )
    return TelegramStatusOut(
        feature_enabled=True,
        connected=ok,
        auth_status=acc.auth_status,
        phone_hint=acc.phone_hint,
        account_id=str(acc.id),
        last_sync_at=acc.last_sync_at,
        awaiting_two_factor=awaiting_2fa,
    )


@router.post("/connect", response_model=TelegramConnectOut)
async def telegram_connect(
    body: TelegramConnectIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramConnectOut:
    _tg_feature()
    err = telethon_import_error()
    if err is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Клиент Telegram не установлен на сервере",
        ) from err
    try:
        api_id_int = int(str(body.api_id).strip())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="api_id должен быть числом",
        ) from e

    api_hash_enc = encryption.encrypt_secret(body.api_hash.strip())
    acc = _user_account(db, user.id)
    phone = body.phone.strip()
    hint = phone_hint_mask(phone)

    if acc is None:
        acc = TelegramAccount(
            owner_id=user.id,
            api_id=str(api_id_int),
            encrypted_api_hash=api_hash_enc,
            phone_hint=hint,
            auth_status=AUTH_PENDING,
        )
        db.add(acc)
        db.flush()
    else:
        acc.api_id = str(api_id_int)
        acc.encrypted_api_hash = api_hash_enc
        acc.phone_hint = hint
        acc.auth_status = AUTH_PENDING
        acc.pending_auth = None

    session_str = None
    if acc.encrypted_session:
        try:
            session_str = encryption.decrypt_secret(acc.encrypted_session)
        except Exception:
            session_str = None

    try:
        new_sess, p_hash = await send_code_request(
            api_id_int,
            body.api_hash.strip(),
            phone,
            session_str,
        )
    except Exception as exc:
        logger.warning("telegram_send_code_failed: %s", exc, exc_info=True)
        acc.auth_status = AUTH_ERROR
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Не удалось отправить код в Telegram. Проверьте api_id, api_hash и номер.",
        ) from exc

    acc.encrypted_session = encryption.encrypt_secret(new_sess)
    acc.pending_auth = {"phone": phone, "phone_code_hash": p_hash}
    acc.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(acc)

    return TelegramConnectOut(
        account_id=str(acc.id),
        need_code=True,
        phone_hint=hint,
        message="Код отправлен в Telegram или по SMS",
    )


@router.post("/verify-code", response_model=TelegramVerifyOut)
async def telegram_verify_code(
    body: TelegramVerifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramVerifyOut:
    _tg_feature()
    err = telethon_import_error()
    if err is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Клиент Telegram не установлен на сервере",
        ) from err

    acc = db.get(TelegramAccount, body.account_id)
    if not acc or acc.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аккаунт не найден")

    pending = acc.pending_auth if isinstance(acc.pending_auth, dict) else {}
    if pending.get("stage") == PENDING_STAGE_2FA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Код уже принят. Введите облачный пароль двухэтапной проверки.",
        )
    phone = pending.get("phone")
    p_hash = pending.get("phone_code_hash")
    if not isinstance(phone, str) or not isinstance(p_hash, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала запросите код (connect)",
        )

    try:
        api_id_int = int(acc.api_id.strip())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Некорректный api_id в записи",
        ) from e

    try:
        api_hash = encryption.decrypt_secret(acc.encrypted_api_hash)
        session_str = encryption.decrypt_secret(acc.encrypted_session or b"")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось прочитать сохранённые учётные данные",
        ) from exc

    try:
        new_sess, sign_status = await sign_in_with_code(
            api_id_int,
            api_hash,
            session_str,
            phone,
            body.code.strip(),
            p_hash,
        )
    except Exception as exc:
        logger.warning("telegram_sign_in_failed: %s", exc, exc_info=True)
        acc.auth_status = AUTH_ERROR
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный код или сессия устарела. Запросите код снова.",
        ) from exc

    acc.encrypted_session = encryption.encrypt_secret(new_sess)
    acc.updated_at = datetime.now(timezone.utc)

    if sign_status == "need_password":
        acc.pending_auth = {"stage": PENDING_STAGE_2FA}
        acc.auth_status = AUTH_PENDING
        db.commit()
        return TelegramVerifyOut(
            status="need_password",
            message="Включена двухэтапная проверка. Введите облачный пароль Telegram.",
        )

    acc.auth_status = AUTH_AUTHORIZED
    acc.pending_auth = None
    db.commit()

    return TelegramVerifyOut(status="authorized", message="Подключение сохранено")


@router.post("/verify-password", response_model=TelegramVerifyOut)
async def telegram_verify_password(
    body: TelegramVerifyPasswordIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramVerifyOut:
    _tg_feature()
    err = telethon_import_error()
    if err is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Клиент Telegram не установлен на сервере",
        ) from err

    acc = db.get(TelegramAccount, body.account_id)
    if not acc or acc.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Аккаунт не найден")

    pending = acc.pending_auth if isinstance(acc.pending_auth, dict) else {}
    if pending.get("stage") != PENDING_STAGE_2FA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала подтвердите код из SMS или Telegram.",
        )

    try:
        api_id_int = int(acc.api_id.strip())
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Некорректный api_id в записи",
        ) from e

    try:
        api_hash = encryption.decrypt_secret(acc.encrypted_api_hash)
        session_str = encryption.decrypt_secret(acc.encrypted_session or b"")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось прочитать сохранённые учётные данные",
        ) from exc

    try:
        final_sess = await sign_in_with_password(
            api_id_int,
            api_hash,
            session_str,
            body.password,
        )
    except InvalidTwoFactorPasswordError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный облачный пароль. Попробуйте снова.",
        ) from exc
    except Exception as exc:
        logger.warning("telegram_sign_in_password_failed: %s", exc, exc_info=True)
        acc.auth_status = AUTH_ERROR
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось завершить вход. Запросите код снова.",
        ) from exc

    acc.encrypted_session = encryption.encrypt_secret(final_sess)
    acc.auth_status = AUTH_AUTHORIZED
    acc.pending_auth = None
    acc.updated_at = datetime.now(timezone.utc)
    db.commit()

    return TelegramVerifyOut(status="authorized", message="Подключение сохранено")


@router.post("/disconnect", response_model=TelegramVerifyOut)
def telegram_disconnect(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramVerifyOut:
    _tg_feature()
    acc = _user_account(db, user.id)
    if acc:
        db.delete(acc)
        db.commit()
    return TelegramVerifyOut(status="disconnected")


@router.get("/sources", response_model=list[TelegramSourceOut])
def list_sources(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TelegramSourceOut]:
    _tg_feature()
    acc = _user_account(db, user.id)
    if not acc:
        return []
    rows = db.scalars(
        select(TelegramSource)
        .where(TelegramSource.account_id == acc.id)
        .order_by(TelegramSource.created_at.desc())
    ).all()
    return [_telegram_source_to_out(r) for r in rows]


@router.post("/sources", response_model=TelegramSourceOut, status_code=status.HTTP_201_CREATED)
async def add_source(
    body: TelegramSourceIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramSourceOut:
    _tg_feature()
    err_imp = telethon_import_error()
    if err_imp is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Клиент Telegram не установлен на сервере",
        ) from err_imp
    acc = _user_account(db, user.id)
    if not acc or acc.auth_status != AUTH_AUTHORIZED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала подключите Telegram-аккаунт",
        )
    raw_link = body.link.strip()
    now = datetime.now(timezone.utc)
    norm = _normalize_telegram_link(raw_link)
    if norm is None:
        row = TelegramSource(
            account_id=acc.id,
            telegram_id=0,
            link=raw_link,
            type="channel",
            display_name=(body.display_name.strip() or raw_link[:200])[:512],
            access_status="invalid",
            is_enabled=True,
            error_message="Неподдерживаемый формат ссылки Telegram",
            last_check_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _telegram_source_to_out(row)
    try:
        api_id_int = int(str(acc.api_id).strip())
        api_hash = encryption.decrypt_secret(acc.encrypted_api_hash)
        session_str = encryption.decrypt_secret(acc.encrypted_session or b"")
    except Exception as exc:
        logger.warning("telegram_credentials_read_failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Не удалось прочитать учётные данные Telegram",
        ) from exc
    try:
        tg_id, src_type, disp, access_st, err_msg = await _probe_telegram_source(
            api_id_int,
            api_hash,
            session_str,
            norm,
        )
    except Exception as exc:
        logger.warning("telegram_probe_failed: %s", exc, exc_info=True)
        st, em = _map_telegram_access_error(exc)
        row = TelegramSource(
            account_id=acc.id,
            telegram_id=0,
            link=raw_link,
            type="channel",
            display_name=(body.display_name.strip() or raw_link[:200])[:512],
            access_status=st,
            is_enabled=True,
            error_message=em,
            last_check_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _telegram_source_to_out(row)
    display_name = (body.display_name.strip() or disp or raw_link)[:512]
    row = TelegramSource(
        account_id=acc.id,
        telegram_id=tg_id,
        link=raw_link,
        type=src_type,
        display_name=display_name,
        access_status=access_st,
        is_enabled=True,
        error_message=err_msg,
        last_check_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _telegram_source_to_out(row)


@router.patch("/sources/{source_id}", response_model=TelegramSourceOut)
def patch_source(
    source_id: uuid.UUID,
    body: TelegramSourcePatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramSourceOut:
    _tg_feature()
    acc = _user_account(db, user.id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет аккаунта")
    row = db.get(TelegramSource, source_id)
    if not row or row.account_id != acc.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if body.is_enabled is not None:
        row.is_enabled = body.is_enabled
    if body.display_name is not None:
        row.display_name = body.display_name.strip() or row.display_name
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _telegram_source_to_out(row)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _tg_feature()
    acc = _user_account(db, user.id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет аккаунта")
    row = db.get(TelegramSource, source_id)
    if not row or row.account_id != acc.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    db.delete(row)
    db.commit()


@router.post("/sources/{source_id}/validate", response_model=TelegramSourceOut)
async def validate_source(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramSourceOut:
    _tg_feature()
    err_imp = telethon_import_error()
    if err_imp is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Клиент Telegram не установлен на сервере",
        ) from err_imp
    acc = _user_account(db, user.id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет аккаунта")
    row = db.get(TelegramSource, source_id)
    if not row or row.account_id != acc.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    now = datetime.now(timezone.utc)
    row.last_check_at = now
    norm = _normalize_telegram_link(row.link)
    if norm is None:
        row.telegram_id = 0
        row.access_status = "invalid"
        row.error_message = "Неподдерживаемый формат ссылки Telegram"
        row.updated_at = now
        db.commit()
        db.refresh(row)
        return _telegram_source_to_out(row)
    if acc.auth_status != AUTH_AUTHORIZED:
        row.access_status = "access_required"
        row.error_message = "Сессия Telegram не авторизована"
        row.updated_at = now
        db.commit()
        db.refresh(row)
        return _telegram_source_to_out(row)
    try:
        api_id_int = int(str(acc.api_id).strip())
        api_hash = encryption.decrypt_secret(acc.encrypted_api_hash)
        session_str = encryption.decrypt_secret(acc.encrypted_session or b"")
    except Exception as exc:
        logger.warning("telegram_credentials_read_failed: %s", exc, exc_info=True)
        row.access_status = "unavailable"
        row.error_message = "Не удалось прочитать учётные данные Telegram"
        row.updated_at = now
        db.commit()
        db.refresh(row)
        return _telegram_source_to_out(row)
    try:
        tg_id, src_type, disp, access_st, err_msg = await _probe_telegram_source(
            api_id_int,
            api_hash,
            session_str,
            norm,
        )
    except Exception as exc:
        logger.warning("telegram_probe_failed: %s", exc, exc_info=True)
        st, em = _map_telegram_access_error(exc)
        row.telegram_id = 0
        row.type = "channel"
        row.access_status = st
        row.error_message = em
        row.updated_at = now
        db.commit()
        db.refresh(row)
        return _telegram_source_to_out(row)
    row.telegram_id = tg_id
    row.type = src_type
    if not row.display_name.strip() and disp:
        row.display_name = disp
    row.access_status = access_st
    row.error_message = err_msg
    row.updated_at = now
    db.commit()
    db.refresh(row)
    return _telegram_source_to_out(row)


@router.post("/sources/{source_id}/sync", response_model=TelegramSyncRunOut)
def trigger_sync(
    source_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TelegramSyncRunOut:
    _tg_feature()
    acc = _user_account(db, user.id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет аккаунта")
    row = db.get(TelegramSource, source_id)
    if not row or row.account_id != acc.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    run = TelegramSyncRun(
        source_id=row.id,
        status="queued",
        messages_processed=0,
        candidates_created=0,
        error_log=None,
        finished_at=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return TelegramSyncRunOut(
        id=str(run.id),
        source_id=str(run.source_id),
        status=run.status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        messages_processed=run.messages_processed,
        candidates_created=run.candidates_created,
        error_log=run.error_log,
    )


@router.get("/sync-runs", response_model=list[TelegramSyncRunOut])
def list_sync_runs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    limit: int = 50,
) -> list[TelegramSyncRunOut]:
    _tg_feature()
    acc = _user_account(db, user.id)
    if not acc:
        return []
    src_ids = db.scalars(
        select(TelegramSource.id).where(TelegramSource.account_id == acc.id)
    ).all()
    if not src_ids:
        return []
    lim = max(1, min(limit, 200))
    runs = db.scalars(
        select(TelegramSyncRun)
        .where(TelegramSyncRun.source_id.in_(src_ids))
        .order_by(TelegramSyncRun.started_at.desc())
        .limit(lim)
    ).all()
    return [
        TelegramSyncRunOut(
            id=str(r.id),
            source_id=str(r.source_id),
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            messages_processed=r.messages_processed,
            candidates_created=r.candidates_created,
            error_log=r.error_log,
        )
        for r in runs
    ]
