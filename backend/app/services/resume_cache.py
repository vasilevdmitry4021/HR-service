"""In-memory TTL-кэш полных данных резюме (снижает повторные запросы к HH)."""

from __future__ import annotations

from typing import Any

from app.services.ttl_cache import TTLCache

_full_resume_cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=3600, max_items=500)


def get_cached_resume(resume_id: str) -> dict[str, Any] | None:
    return _full_resume_cache.get(resume_id)


def cache_resume(resume_id: str, data: dict[str, Any]) -> None:
    _full_resume_cache.set(resume_id, data)
