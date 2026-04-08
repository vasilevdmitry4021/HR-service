from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HHConnectOut(BaseModel):
    authorization_url: str


class HHConnectCallbackIn(BaseModel):
    code: str
    state: str | None = None


class HHConnectSuccessOut(BaseModel):
    status: str = "connected"
    hh_user_id: str
    expires_at: datetime


class HHStatusOut(BaseModel):
    connected: bool
    hh_user_id: str | None = None
    employer_name: str | None = None
    access_expires_at: datetime | None = None
    services: dict[str, Any] | None = None
    message: str | None = None


class HHCredentialsIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=200)
    client_secret: str = Field(min_length=1, max_length=200)
    redirect_uri: str | None = None


class HHCredentialsStatusOut(BaseModel):
    configured: bool
    redirect_uri: str


class HHCredentialsPutOut(BaseModel):
    status: str = "ok"
