"""Юнит-тесты снимка поиска (без PostgreSQL)."""

from __future__ import annotations

import pytest

from app.services.search_snapshot_cache import (
    SearchSnapshotData,
    get_snapshot,
    replace_snapshot,
    reset_snapshots_for_tests,
    save_snapshot,
)


@pytest.fixture(autouse=True)
def _reset_snapshots() -> None:
    reset_snapshots_for_tests()
    yield
    reset_snapshots_for_tests()


def test_save_replace_snapshot_flags() -> None:
    data = SearchSnapshotData(
        items=[{"id": "1", "llm_score": None}],
        found_raw_hh=1,
        loaded_from_hh=1,
        parsed_params={},
        query="q",
        filters=None,
        evaluated=False,
        analyzed=False,
    )
    sid = save_snapshot("user-a", data)
    assert get_snapshot("user-a", sid) is not None

    updated = SearchSnapshotData(
        items=[{"id": "1", "llm_analysis": {"llm_score": 80}, "llm_score": 80}],
        found_raw_hh=1,
        loaded_from_hh=1,
        parsed_params={},
        query="q",
        filters=None,
        evaluated=True,
        analyzed=True,
    )
    assert replace_snapshot("user-a", sid, updated) is True
    got = get_snapshot("user-a", sid)
    assert got is not None
    assert got.evaluated is True
    assert got.analyzed is True
    assert got.items[0].get("llm_analysis", {}).get("llm_score") == 80


def test_replace_unknown_snapshot_returns_false() -> None:
    dummy = SearchSnapshotData(
        items=[],
        found_raw_hh=0,
        loaded_from_hh=0,
        parsed_params={},
        query="",
        filters=None,
    )
    assert replace_snapshot("u", "00000000-0000-0000-0000-000000000000", dummy) is False
