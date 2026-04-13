"""Снимок выдачи поиска: в памяти процесса или в Redis (общий кэш между репликами)."""

from __future__ import annotations

import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from app.config import settings
from app.services.ttl_cache import TTLCache

logger = logging.getLogger(__name__)

_SNAPSHOT_KEY_PREFIX = "hr:snapshot:v1"


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

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "items": self.items,
            "found_raw_hh": self.found_raw_hh,
            "loaded_from_hh": self.loaded_from_hh,
            "parsed_params": self.parsed_params,
            "query": self.query,
            "filters": self.filters,
            "evaluated": self.evaluated,
            "analyzed": self.analyzed,
            "source_scope": self.source_scope,
            "found_telegram": self.found_telegram,
        }

    @staticmethod
    def from_json_dict(d: dict[str, Any]) -> SearchSnapshotData:
        return SearchSnapshotData(
            items=list(d.get("items") or []),
            found_raw_hh=d.get("found_raw_hh"),
            loaded_from_hh=int(d.get("loaded_from_hh") or 0),
            parsed_params=dict(d.get("parsed_params") or {}),
            query=str(d.get("query") or ""),
            filters=d.get("filters"),
            evaluated=bool(d.get("evaluated", False)),
            analyzed=bool(d.get("analyzed", False)),
            source_scope=str(d.get("source_scope") or "hh"),
            found_telegram=d.get("found_telegram"),
        )


class SearchSnapshotStoreBase(ABC):
    @abstractmethod
    def get(self, user_id: str, snapshot_id: str) -> SearchSnapshotData | None: ...

    @abstractmethod
    def set(self, user_id: str, data: SearchSnapshotData) -> str: ...

    @abstractmethod
    def replace(self, user_id: str, snapshot_id: str, data: SearchSnapshotData) -> bool: ...

    @abstractmethod
    def clear(self) -> None: ...


class SearchSnapshotStore(SearchSnapshotStoreBase):
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


class RedisSearchSnapshotStore(SearchSnapshotStoreBase):
    """Ключи snapshot:{user_id}:{uuid}, порядок снимков на пользователя — список в Redis."""

    def __init__(
        self,
        *,
        redis_url: str,
        ttl_seconds: float,
        max_per_user: int,
    ) -> None:
        import redis as redis_lib

        self._redis = redis_lib.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5.0,
            socket_timeout=5.0,
        )
        self._ttl = max(1, int(ttl_seconds))
        self._max_per_user = max(1, int(max_per_user))
        self._redis.ping()

    def _data_key(self, user_id: str, sid: str) -> str:
        return f"{_SNAPSHOT_KEY_PREFIX}:data:{user_id}:{sid}"

    def _index_key(self, user_id: str) -> str:
        return f"{_SNAPSHOT_KEY_PREFIX}:index:{user_id}"

    def get(self, user_id: str, snapshot_id: str) -> SearchSnapshotData | None:
        parsed = _parse_snapshot_uuid(snapshot_id)
        if parsed is None:
            return None
        sid = str(parsed)
        raw = self._redis.get(self._data_key(user_id, sid))
        if not raw:
            return None
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(obj, dict):
            return None
        return SearchSnapshotData.from_json_dict(obj)

    def set(self, user_id: str, data: SearchSnapshotData) -> str:
        sid = str(uuid.uuid4())
        dk = self._data_key(user_id, sid)
        ik = self._index_key(user_id)
        payload = json.dumps(data.to_json_dict(), ensure_ascii=False)
        pipe = self._redis.pipeline(transaction=True)
        pipe.setex(dk, self._ttl, payload)
        pipe.rpush(ik, sid)
        pipe.expire(ik, self._ttl + 60)
        pipe.execute()

        while self._redis.llen(ik) > self._max_per_user:
            old = self._redis.lpop(ik)
            if old:
                self._redis.delete(self._data_key(user_id, old))
        return sid

    def replace(self, user_id: str, snapshot_id: str, data: SearchSnapshotData) -> bool:
        parsed = _parse_snapshot_uuid(snapshot_id)
        if parsed is None:
            return False
        sid = str(parsed)
        dk = self._data_key(user_id, sid)
        if not self._redis.exists(dk):
            return False
        payload = json.dumps(data.to_json_dict(), ensure_ascii=False)
        self._redis.setex(dk, self._ttl, payload)
        return True

    def clear(self) -> None:
        pattern = f"{_SNAPSHOT_KEY_PREFIX}:*"
        cursor = 0
        while True:
            cursor, keys = self._redis.scan(cursor, match=pattern, count=256)
            if keys:
                self._redis.delete(*keys)
            if cursor == 0:
                break


def _parse_snapshot_uuid(snapshot_id: str) -> uuid.UUID | None:
    s = (snapshot_id or "").strip()
    if not s:
        return None
    try:
        return uuid.UUID(s)
    except ValueError:
        return None


_store: SearchSnapshotStoreBase | None = None
_store_lock = Lock()


def _get_store() -> SearchSnapshotStoreBase:
    global _store
    with _store_lock:
        if _store is None:
            url = (settings.redis_url or "").strip()
            if url:
                try:
                    _store = RedisSearchSnapshotStore(
                        redis_url=url,
                        ttl_seconds=float(settings.search_snapshot_ttl_seconds),
                        max_per_user=settings.search_snapshot_max_per_user,
                    )
                    logger.info("search_snapshots: using Redis backend")
                except Exception:
                    logger.exception(
                        "search_snapshots: Redis недоступен, используется память процесса",
                    )
                    _store = SearchSnapshotStore(
                        ttl_seconds=float(settings.search_snapshot_ttl_seconds),
                        max_per_user=settings.search_snapshot_max_per_user,
                    )
            else:
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
        _store = None
