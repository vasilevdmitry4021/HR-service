"""Объединение выдач HH и Telegram: дедупликация по id."""

from __future__ import annotations

from app.api.search import _merge_hh_telegram


def test_merge_prefers_first_occurrence_same_id() -> None:
    hh = {"id": "dup", "source_type": "hh", "title": "HH"}
    tg = {"id": "dup", "source_type": "telegram", "title": "TG"}
    out = _merge_hh_telegram([hh], [tg])
    assert len(out) == 1
    assert out[0]["source_type"] == "hh"


def test_merge_concat_unique_ids() -> None:
    out = _merge_hh_telegram(
        [{"id": "a", "source_type": "hh"}],
        [{"id": "b", "source_type": "telegram"}],
    )
    assert len(out) == 2
    assert {x["id"] for x in out} == {"a", "b"}
