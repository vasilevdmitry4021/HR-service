from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr


class IntegrationEditorOut(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool
    can_edit_integration_settings: bool


class AddIntegrationEditorIn(BaseModel):
    email: EmailStr
