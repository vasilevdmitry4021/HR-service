"""Разрешение строк в идентификаторы справочников e-staff (get_voc) и нормализация поиска."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Callable, Coroutine

from app.config import settings
from app.services.ttl_cache import TTLCache

VocItem = dict[str, Any]
FetchVocFn = Callable[[str], Coroutine[Any, Any, list[VocItem]]]

_voc_list_cache: TTLCache[list[VocItem]] | None = None


def voc_cache_key(server_name: str, api_token: str, voc_id: str) -> str:
    tok_hash = hashlib.sha256(api_token.encode("utf-8")).hexdigest()[:24]
    return f"{server_name.strip()}\0{tok_hash}\0{voc_id.strip()}"


def _get_voc_ttl_cache() -> TTLCache[list[VocItem]]:
    global _voc_list_cache
    if _voc_list_cache is None:
        ttl = max(30.0, float(settings.estaff_voc_cache_ttl_seconds))
        _voc_list_cache = TTLCache[list[VocItem]](
            ttl_seconds=ttl,
            max_items=max(32, settings.estaff_voc_cache_max_entries),
        )
    return _voc_list_cache


def parse_get_voc_response(parsed: Any) -> list[VocItem]:
    """Извлекает список {id, name, ...} из ответа get_voc (ключ списка динамический)."""
    if not isinstance(parsed, dict):
        return []
    if parsed.get("success") is False:
        return []
    out: list[VocItem] = []
    for key, val in parsed.items():
        if key == "success":
            continue
        if not isinstance(val, list):
            continue
        for el in val:
            if isinstance(el, dict) and el.get("id") is not None:
                out.append(el)
        if out:
            break
    return out


def normalize_vocab_label(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^(г\.|г\s+|гор\.|город\s+)", "", s, flags=re.IGNORECASE)
    return s.strip()


def _item_name(item: VocItem) -> str:
    n = item.get("name")
    if isinstance(n, str):
        return n
    return str(n or "")


def _item_id_str(item: VocItem) -> str | None:
    v = item.get("id")
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return str(int(v))
    s = str(v).strip()
    return s or None


@dataclass(frozen=True)
class VocResolveOutcome:
    id: str | None
    reason: str | None
    """None если найден ровно один id; иначе код: not_found | ambiguous | empty_query."""


def resolve_vocab_id(
    items: list[VocItem],
    query: str,
    *,
    field_name: str,
    allow_prefix: bool = False,
) -> VocResolveOutcome:
    """Точное совпадение по нормализованному name; при allow_prefix — одно однозначное начало строки."""
    q_raw = (query or "").strip()
    if not q_raw:
        return VocResolveOutcome(None, "empty_query")

    nq = normalize_vocab_label(q_raw)
    if not nq:
        return VocResolveOutcome(None, "empty_query")

    exact: list[str] = []
    for it in items:
        name = normalize_vocab_label(_item_name(it))
        if not name:
            continue
        if name == nq:
            sid = _item_id_str(it)
            if sid:
                exact.append(sid)

    exact_unique = list(dict.fromkeys(exact))
    if len(exact_unique) > 1:
        return VocResolveOutcome(None, "ambiguous")
    if len(exact_unique) == 1:
        return VocResolveOutcome(exact_unique[0], None)

    if not allow_prefix:
        return VocResolveOutcome(None, "not_found")

    prefix_ids: list[str] = []
    for it in items:
        name = normalize_vocab_label(_item_name(it))
        if not name:
            continue
        if name.startswith(nq) or nq.startswith(name):
            sid = _item_id_str(it)
            if sid:
                prefix_ids.append(sid)

    prefix_unique = list(dict.fromkeys(prefix_ids))
    if len(prefix_unique) == 1:
        return VocResolveOutcome(prefix_unique[0], None)
    if len(prefix_unique) > 1:
        return VocResolveOutcome(None, "ambiguous")
    return VocResolveOutcome(None, "not_found")


async def get_vocabulary_items_cached(
    server_name: str,
    api_token: str,
    voc_id: str,
    fetch_voc: FetchVocFn,
) -> list[VocItem]:
    key = voc_cache_key(server_name, api_token, voc_id)
    cache = _get_voc_ttl_cache()
    hit = cache.get(key)
    if hit is not None:
        return hit
    items = await fetch_voc(voc_id)
    cache.set(key, items)
    return items


def clear_vocabulary_cache() -> None:
    c = _get_voc_ttl_cache()
    c.clear()
