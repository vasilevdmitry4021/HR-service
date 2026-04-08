"""Простой in-memory TTL-кэш с ограничением размера (FIFO при переполнении)."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_seconds: float, max_items: int = 256) -> None:
        self._ttl = ttl_seconds
        self._max = max(1, max_items)
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        now = time.monotonic()
        item = self._data.get(key)
        if item is None:
            return None
        ts, val = item
        if now - ts > self._ttl:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return val

    def set(self, key: str, value: T) -> None:
        now = time.monotonic()
        while len(self._data) >= self._max:
            self._data.popitem(last=False)
        self._data[key] = (now, value)
        self._data.move_to_end(key)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()
