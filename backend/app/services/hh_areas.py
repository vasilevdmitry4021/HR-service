from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Any

import httpx

from app.services.hh_client import HH_API, USER_AGENT

logger = logging.getLogger(__name__)

RUSSIA_COUNTRY_ID = 113
CACHE_TTL_SEC = 86_400
STALE_EXTENSION_SEC = 3_600

_lock = Lock()
_cache_expires_at: float = 0.0
_cache_rows: list[dict[str, Any]] = []


def _area_id(raw: Any) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def flatten_area_branch(nodes: list[Any], prefix: str = "") -> list[dict[str, Any]]:
    """Преобразует поддерево HH в плоский список с путём в названии (родитель — … — город)."""
    out: list[dict[str, Any]] = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        aid = _area_id(n.get("id"))
        name = str(n.get("name") or "").strip()
        if aid is None or not name:
            continue
        path = f"{prefix} — {name}" if prefix else name
        out.append({"id": aid, "name": path})
        children = n.get("areas")
        if isinstance(children, list) and children:
            out.extend(flatten_area_branch(children, path))
    return out


def extract_russia_areas(data: list[Any]) -> list[dict[str, Any]]:
    """Берёт только ветку страны Россия (id=113), включая саму страну."""
    for item in data:
        if not isinstance(item, dict):
            continue
        if _area_id(item.get("id")) != RUSSIA_COUNTRY_ID:
            continue
        root_name = str(item.get("name") or "Россия").strip()
        acc: list[dict[str, Any]] = [{"id": RUSSIA_COUNTRY_ID, "name": root_name}]
        children = item.get("areas")
        if isinstance(children, list) and children:
            acc.extend(flatten_area_branch(children, root_name))
        acc.sort(key=lambda x: str(x["name"]).casefold())
        return acc
    return []


async def fetch_russia_areas_from_hh() -> list[dict[str, Any]]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HH_API}/areas",
            headers={"User-Agent": USER_AGENT},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, list):
        return []
    return extract_russia_areas(data)


async def get_russia_areas_cached() -> list[dict[str, Any]]:
    """Кэш в памяти процесса; при сбое HH отдаётся устаревший кэш, если он есть."""
    global _cache_expires_at, _cache_rows
    now = time.monotonic()
    with _lock:
        if _cache_rows and now < _cache_expires_at:
            return list(_cache_rows)

    stale_copy = list(_cache_rows) if _cache_rows else []
    try:
        rows = await fetch_russia_areas_from_hh()
    except (httpx.HTTPError, ValueError, TypeError) as e:
        logger.warning("hh areas fetch failed: %s", e)
        if stale_copy:
            with _lock:
                _cache_expires_at = now + STALE_EXTENSION_SEC
            return stale_copy
        raise
    if not rows:
        if stale_copy:
            with _lock:
                _cache_expires_at = now + STALE_EXTENSION_SEC
            return stale_copy
        return []

    with _lock:
        _cache_rows = rows
        _cache_expires_at = now + CACHE_TTL_SEC
    return list(_cache_rows)
