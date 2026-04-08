from __future__ import annotations

import pytest

from app.services import hh_areas


def test_flatten_area_branch_builds_path() -> None:
    nodes = [
        {
            "id": "1",
            "name": "Москва",
            "areas": [{"id": "100", "name": "Зеленоград", "areas": []}],
        }
    ]
    flat = hh_areas.flatten_area_branch(nodes, "Россия")
    assert flat == [
        {"id": 1, "name": "Россия — Москва"},
        {"id": 100, "name": "Россия — Москва — Зеленоград"},
    ]


def test_extract_russia_areas_sorts_by_name() -> None:
    data = [
        {
            "id": "999",
            "name": "Другая страна",
            "areas": [],
        },
        {
            "id": "113",
            "name": "Россия",
            "areas": [
                {"id": "2", "name": "Санкт-Петербург", "areas": []},
                {"id": "1", "name": "Москва", "areas": []},
            ],
        },
    ]
    out = hh_areas.extract_russia_areas(data)
    ids = [x["id"] for x in out]
    assert 113 in ids
    assert 1 in ids
    assert 2 in ids
    names = [x["name"] for x in out if x["id"] != 113]
    assert names == sorted(names, key=str.casefold)


@pytest.mark.asyncio
async def test_get_russia_areas_cached_uses_http(monkeypatch: pytest.MonkeyPatch) -> None:
    hh_areas._cache_rows = []
    hh_areas._cache_expires_at = 0.0

    sample = [
        {
            "id": "113",
            "name": "Россия",
            "areas": [{"id": "1", "name": "Москва", "areas": []}],
        }
    ]

    async def fake_fetch() -> list[dict]:
        return hh_areas.extract_russia_areas(sample)

    monkeypatch.setattr(hh_areas, "fetch_russia_areas_from_hh", fake_fetch)

    first = await hh_areas.get_russia_areas_cached()
    second = await hh_areas.get_russia_areas_cached()
    assert len(first) >= 2
    assert first == second
