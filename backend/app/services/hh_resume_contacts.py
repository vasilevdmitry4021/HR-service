"""Извлечение контактов из сырого ответа API HeadHunter (резюме)."""

from __future__ import annotations

import re
from typing import Any


def contacts_from_hh_raw(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    email: str | None = None
    phone: str | None = None
    items = raw.get("contact")
    if not isinstance(items, list):
        return None, None
    for c in items:
        if not isinstance(c, dict):
            continue
        t = c.get("type")
        type_id = ""
        if isinstance(t, dict):
            type_id = str(t.get("id") or "").lower()
        elif isinstance(t, str):
            type_id = t.lower()
        val: Any = (
            c.get("value")
            or c.get("formatted")
            or c.get("contact")
            or c.get("number")
        )
        if isinstance(val, dict):
            val = val.get("formatted") or val.get("number") or val.get("email")
        if not isinstance(val, str) or not val.strip():
            continue
        s = val.strip()
        if type_id == "email" or ("@" in s and "." in s):
            email = email or s
        elif type_id in ("cell", "phone", "work", "home", "whatsapp"):
            phone = phone or s
        elif not phone and re.search(r"[\d+()\- ]{10,}", s):
            phone = phone or s
    return email, phone
