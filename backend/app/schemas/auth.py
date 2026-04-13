from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RegisterOut(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class UserMeOut(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool
    is_super_admin: bool
    can_write_integration_settings: bool
    can_manage_integration_editors: bool
    can_revoke_integration_editor_access: bool

    model_config = {"from_attributes": True}


class OAuthExchangeIn(BaseModel):
    code: str = Field(min_length=8, max_length=512)
