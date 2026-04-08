"""Кэш результатов LLM-анализа: тот же текст в списке поиска и в карточке без повторного вызова модели."""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

from app.config import settings

_lock = threading.Lock()
_entries: dict[str, tuple[float, dict[str, Any]]] = {}


def _normalized_query(q: str) -> str:
    return (q or "").strip()


def _entry_key(user_id: str, resume_id: str, query: str) -> str:
    nq = _normalized_query(query)
    raw = f"{user_id}\0{resume_id}\0{nq}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _prune_unlocked(now: float) -> None:
    max_n = max(1, settings.llm_analysis_cache_max_entries)
    dead = [k for k, (exp, _) in _entries.items() if exp <= now]
    for k in dead:
        del _entries[k]

    while len(_entries) > max_n:
        if not _entries:
            break
        oldest = min(_entries.items(), key=lambda kv: kv[1][0])
        del _entries[oldest[0]]


def store_for_resume_ids(
    user_id: str,
    resume_ids: list[str],
    search_query: str,
    analysis: dict[str, Any],
) -> None:
    """Один анализ для нескольких идентификаторов одного резюме (id / hh_resume_id)."""
    nq = _normalized_query(search_query)
    if not nq or not resume_ids:
        return

    ttl = max(60, settings.llm_analysis_cache_ttl_seconds)
    expires = time.monotonic() + ttl
    uid = str(user_id)

    with _lock:
        now = time.monotonic()
        _prune_unlocked(now)
        for rid in resume_ids:
            s = str(rid).strip()
            if not s:
                continue
            k = _entry_key(uid, s, nq)
            _entries[k] = (expires, dict(analysis))


def get_cached(user_id: str, resume_id: str, search_query: str) -> dict[str, Any] | None:
    nq = _normalized_query(search_query)
    if not nq:
        return None

    uid = str(user_id)
    rid = str(resume_id).strip()
    if not rid:
        return None

    k = _entry_key(uid, rid, nq)
    with _lock:
        now = time.monotonic()
        _prune_unlocked(now)
        row = _entries.get(k)
        if not row:
            return None
        exp, data = row
        if exp <= now:
            del _entries[k]
            return None
        return dict(data)


def resume_lookup_keys(resume: dict[str, Any]) -> list[str]:
    """Идентификаторы, по которым клиент может открыть карточку."""
    out: list[str] = []
    for key in ("id", "hh_resume_id"):
        v = resume.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out.append(s)
    return list(dict.fromkeys(out))
