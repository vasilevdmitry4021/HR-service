from __future__ import annotations

import copy
import time
from typing import TYPE_CHECKING, Any

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
from app.services import llm_client
from app.services import mock_llm
from app.services.ttl_cache import TTLCache

_parse_cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60.0, max_items=384)


def parse_natural_query(
    query: str,
    force_reparse: bool = False,
    db: "Session | None" = None,
) -> tuple[dict[str, Any], float, int]:
    q = query.strip()
    start = time.perf_counter()
    if force_reparse and q in _parse_cache._data:
        del _parse_cache._data[q]
    if not force_reparse:
        cached = _parse_cache.get(q) if q else None
        if cached is not None:
            parsed = copy.deepcopy(cached)
            if settings.feature_use_mock_llm:
                confidence = 0.85 + min(0.1, len(q) / 500.0)
                confidence = min(0.95, confidence)
            else:
                confidence = 0.75
            return parsed, confidence, 0
    if settings.feature_use_mock_llm:
        parsed = mock_llm.parse_query_mock(q)
    else:
        parsed = llm_client.parse_query_via_llm(q, db)
    # Не кэшируем пустой результат — при следующем запросе попробуем снова
    has_content = any(
        v is not None and v != "" and not (isinstance(v, list) and len(v) == 0)
        for v in parsed.values()
    )
    if has_content:
        _parse_cache.set(q, copy.deepcopy(parsed))
    if settings.feature_use_mock_llm:
        confidence = 0.85 + min(0.1, len(q) / 500.0)
        confidence = min(0.95, confidence)
    else:
        confidence = 0.75
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return parsed, confidence, elapsed_ms
