"""In-memory TTL-кэш полных данных резюме (снижает повторные запросы к HH).

Ключ включает идентификатор пользователя, чтобы данные с контактами из одного
рабочего места HH не пересекались между учётными записями.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.services.ttl_cache import TTLCache

_full_resume_cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=3600, max_items=500)


def _cache_key(user_id: uuid.UUID, resume_id: str) -> str:
    return f"{user_id}:{resume_id}"


def get_cached_resume(user_id: uuid.UUID, resume_id: str) -> dict[str, Any] | None:
    return _full_resume_cache.get(_cache_key(user_id, resume_id))


def cache_resume(user_id: uuid.UUID, resume_id: str, data: dict[str, Any]) -> None:
    _full_resume_cache.set(_cache_key(user_id, resume_id), data)
