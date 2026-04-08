from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    YANDEX_GPT = "yandex_gpt"
    GIGACHAT = "gigachat"


class LLMSettingsIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: LLMProvider
    endpoint: str | None = None
    api_key: str | None = None
    model: str = Field(..., min_length=1, max_length=256)
    fast_model: str | None = Field(None, max_length=256)
    folder_id: str | None = Field(None, max_length=128)
    client_id: str | None = Field(None, max_length=256)
    client_secret: str | None = Field(None, max_length=512)
    scope: str | None = Field(None, max_length=256)


class LLMSettingsStatusOut(BaseModel):
    configured: bool
    provider: str | None = None
    model: str | None = None
    fast_model: str | None = None
    endpoint_masked: str | None = None
    folder_id: str | None = None
    client_id: str | None = None
    scope: str | None = None


class LLMSettingsGetOut(LLMSettingsStatusOut):
    """Полные несекретные поля для формы настроек (GET)."""

    endpoint: str | None = None


class LLMTestOut(BaseModel):
    success: bool
    message: str
    response_time_ms: int | None = None
