"""In-memory снимок выдачи поиска: полный список кандидатов и метаданные по пользователю."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.config import settings
from app.services.ttl_cache import TTLCache


@dataclass(frozen=True)
class SearchSnapshotData:
    """Сериализованные CandidateOut (словари) после обработки, плюс метаданные."""

    items: list[dict[str, Any]]
    found_raw_hh: int | None
    loaded_from_hh: int
    parsed_params: dict[str, Any]
    query: str
    filters: dict[str, Any] | None
    evaluated: bool = False
    analyzed: bool = False
    source_scope: str = "hh"
    found_telegram: int | None = None


class SearchSnapshotStore:
    """Ключ хранения: user_id:snapshot_uuid. Лимит числа снимков на пользователя."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        max_per_user: int,
        global_max_keys: int = 10_000,
    ) -> None:
        self._ttl = max(1.0, float(ttl_seconds))
        self._max_per_user = max(1, int(max_per_user))
        self._cache: TTLCache[SearchSnapshotData] = TTLCache(
            ttl_seconds=self._ttl,
            max_items=max(self._max_per_user * 500, global_max_keys),
        )
        self._user_order: dict[str, OrderedDict[str, None]] = {}
        self._lock = Lock()

    def _composite_key(self, user_id: str, snapshot_id: str) -> str:
        return f"{user_id}:{snapshot_id}"

    def get(self, user_id: str, snapshot_id: str) -> SearchSnapshotData | None:
        parsed = _parse_snapshot_uuid(snapshot_id)
        if parsed is None:
            return None
        sid = str(parsed)
        key = self._composite_key(user_id, sid)
        with self._lock:
            return self._cache.get(key)

    def set(self, user_id: str, data: SearchSnapshotData) -> str:
        snap_uuid = uuid.uuid4()
        sid = str(snap_uuid)
        key = self._composite_key(user_id, sid)
        with self._lock:
            self._cache.set(key, data)
            od = self._user_order.setdefault(user_id, OrderedDict())
            od[sid] = None
            od.move_to_end(sid)
            while len(od) > self._max_per_user:
                oldest_sid, _ = od.popitem(last=False)
                self._cache.delete(self._composite_key(user_id, oldest_sid))
        return sid

    def replace(self, user_id: str, snapshot_id: str, data: SearchSnapshotData) -> bool:
        """Заменить данные существующего снимка (тот же идентификатор, обновление TTL)."""
        parsed = _parse_snapshot_uuid(snapshot_id)
        if parsed is None:
            return False
        sid = str(parsed)
        key = self._composite_key(user_id, sid)
        with self._lock:
            if self._cache.get(key) is None:
                return False
            self._cache.set(key, data)
        return True

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._user_order.clear()


def _parse_snapshot_uuid(snapshot_id: str) -> uuid.UUID | None:
    s = (snapshot_id or "").strip()
    if not s:
        return None
    try:
        return uuid.UUID(s)
    except ValueError:
        return None


_store: SearchSnapshotStore | None = None
_store_lock = Lock()


def _get_store() -> SearchSnapshotStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = SearchSnapshotStore(
                ttl_seconds=float(settings.search_snapshot_ttl_seconds),
                max_per_user=settings.search_snapshot_max_per_user,
            )
        return _store


def get_snapshot(user_id: str, snapshot_id: str) -> SearchSnapshotData | None:
    return _get_store().get(user_id, snapshot_id)


def save_snapshot(user_id: str, data: SearchSnapshotData) -> str:
    return _get_store().set(user_id, data)


def replace_snapshot(user_id: str, snapshot_id: str, data: SearchSnapshotData) -> bool:
    return _get_store().replace(user_id, snapshot_id, data)


def reset_snapshots_for_tests() -> None:
    """Очистка глобального хранилища (только тесты)."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.clear()
