from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TelegramStatusOut(BaseModel):
    feature_enabled: bool
    connected: bool
    auth_status: str | None = None
    phone_hint: str | None = None
    account_id: str | None = None
    last_sync_at: datetime | None = None
    awaiting_two_factor: bool | None = Field(
        default=None,
        description="True — после кода нужен облачный пароль (2FA)",
    )


class TelegramConnectIn(BaseModel):
    api_id: str = Field(min_length=1, max_length=64)
    api_hash: str = Field(min_length=1, max_length=256)
    phone: str = Field(min_length=5, max_length=32)


class TelegramConnectOut(BaseModel):
    account_id: str
    need_code: bool = True
    phone_hint: str | None = None
    message: str | None = None


class TelegramVerifyIn(BaseModel):
    account_id: uuid.UUID
    code: str = Field(min_length=3, max_length=16)


class TelegramVerifyPasswordIn(BaseModel):
    account_id: uuid.UUID
    password: str = Field(min_length=1, max_length=256)


class TelegramVerifyOut(BaseModel):
    status: str
    message: str | None = None


class TelegramSourceIn(BaseModel):
    link: str = Field(
        min_length=1,
        max_length=1024,
        description="Ссылка t.me / telegram.me, @username или имя публичного канала",
    )
    telegram_id: int | None = Field(
        default=None,
        description="Не используется: идентификатор определяется по ссылке и сессии",
    )
    type: str | None = Field(
        default=None,
        max_length=32,
        description="Устарело: тип выставляется автоматически (channel | group | chat)",
    )
    display_name: str = Field(
        default="",
        max_length=512,
        description="Если пусто — подставляется название из Telegram",
    )


class TelegramSourcePatchIn(BaseModel):
    is_enabled: bool | None = None
    display_name: str | None = Field(default=None, max_length=512)


class TelegramSourceOut(BaseModel):
    id: str
    account_id: str
    telegram_id: int
    link: str
    type: str
    display_name: str
    access_status: str
    is_enabled: bool
    last_message_id: int | None = None
    last_check_at: datetime | None = None
    last_sync_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TelegramSyncRunOut(BaseModel):
    id: str
    source_id: str
    status: str = Field(
        description="queued — в очереди; running — выполняется; completed | failed — завершён",
    )
    started_at: datetime
    finished_at: datetime | None = None
    messages_processed: int
    candidates_created: int
    error_log: list[Any] | dict[str, Any] | None = Field(
        default=None,
        description="При ошибке — объект с полем error (текст); иные диагностические поля по необходимости",
    )

    model_config = {"from_attributes": True}
