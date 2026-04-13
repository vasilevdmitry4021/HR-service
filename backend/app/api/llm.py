from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_settings_admin
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.llm import (
    LLMProvider,
    LLMSettingsGetOut,
    LLMSettingsIn,
    LLMTestOut,
)
from app.services import encryption, llm_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


def _merge_llm_payload(existing: dict | None, body: LLMSettingsIn) -> dict:
    data = dict(existing) if isinstance(existing, dict) else {}
    incoming = body.model_dump(exclude_none=True, mode="json")

    # Пустая строка для секретов — оставляем прежнее значение
    for secret_key in ("api_key", "client_secret"):
        v = incoming.get(secret_key)
        if isinstance(v, str) and not v.strip():
            incoming.pop(secret_key, None)
            if data.get(secret_key):
                incoming[secret_key] = data[secret_key]

    data.update(incoming)
    fm = data.get("fast_model")
    if isinstance(fm, str) and not fm.strip():
        data["fast_model"] = None
    for k in ("llm_search_batch_size", "llm_fast_batch_size", "llm_detailed_top_n"):
        data.pop(k, None)
    return data


@router.get("/settings", response_model=LLMSettingsGetOut)
def get_llm_settings(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LLMSettingsGetOut:
    stored = llm_client.get_llm_credentials_from_db(db)
    cfg = llm_client.get_llm_config(db)
    conn_ok = llm_client.llm_connection_configured(db)
    ep = (cfg.endpoint or "").strip()
    prov = str(stored.get("provider")) if stored and stored.get("provider") else cfg.provider
    if stored:
        ep = (str(stored.get("endpoint") or cfg.endpoint or "")).strip()
    return LLMSettingsGetOut(
        configured=conn_ok,
        provider=prov,
        model=str(stored.get("model") or cfg.model) if stored else cfg.model,
        fast_model=str(stored.get("fast_model") or cfg.fast_model) if stored else cfg.fast_model,
        endpoint_masked=llm_client.mask_endpoint(ep) if ep else None,
        endpoint=ep or None,
        folder_id=cfg.folder_id,
        client_id=cfg.client_id,
        scope=cfg.scope,
    )


@router.put("/settings")
def put_llm_settings(
    body: LLMSettingsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_settings_admin),
) -> dict[str, str]:
    existing = llm_client.get_llm_credentials_from_db(db)
    merged = _merge_llm_payload(existing, body)

    if merged.get("provider") == LLMProvider.YANDEX_GPT.value:
        if not (str(merged.get("folder_id") or "").strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для YandexGPT укажите идентификатор каталога (folder_id).",
            )
        if not (str(merged.get("api_key") or "").strip()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для YandexGPT укажите API-ключ.",
            )
    if merged.get("provider") == LLMProvider.GIGACHAT.value:
        if not (str(merged.get("client_id") or "").strip()) or not (
            str(merged.get("client_secret") or "").strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Для GigaChat укажите client_id и client_secret.",
            )

    blob = encryption.encrypt_json(merged)
    row = db.scalars(
        select(SystemSettings).where(SystemSettings.key == llm_client.LLM_CREDENTIALS_KEY)
    ).first()
    if row:
        row.encrypted_value = blob
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            SystemSettings(
                key=llm_client.LLM_CREDENTIALS_KEY,
                encrypted_value=blob,
            )
        )
    db.commit()
    logger.info("llm_settings_updated", extra={"user_id": str(user.id)})
    return {"status": "ok"}


@router.post("/test", response_model=LLMTestOut)
def post_llm_test(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> LLMTestOut:
    ok, message, ms = llm_client.test_llm_connection(db)
    return LLMTestOut(success=ok, message=message, response_time_ms=ms)
