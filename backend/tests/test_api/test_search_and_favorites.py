from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.services import search_snapshot_cache


@pytest.fixture(autouse=True)
def _reset_search_snapshots() -> None:
    search_snapshot_cache.reset_snapshots_for_tests()
    yield
    search_snapshot_cache.reset_snapshots_for_tests()


def _make_mock_resumes(n: int) -> list[dict]:
    return [
        {
            "id": f"mock-{i}",
            "hh_resume_id": f"hh-mock-{i:03d}",
            "title": "Developer",
            "full_name": f"User {i}",
            "age": 30,
            "experience_years": 5,
            "salary": {"amount": 200000, "currency": "RUR"},
            "skills": ["Python"],
            "area": "Москва",
        }
        for i in range(n)
    ]


def test_evaluate_snapshot_updates_items(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """POST evaluate подменяет llm_score у строк снимка (мок evaluate_all_resumes)."""

    async def fake_eval(
        access: str | None,
        resumes: list,
        parsed_params: dict,
        db: object,
    ) -> list[dict]:
        out: list[dict] = []
        for r in resumes:
            d = dict(r)
            d["llm_score"] = 77
            d["llm_analysis"] = None
            out.append(d)
        return out

    async def fake_search(*args: object, **kwargs: object) -> tuple[list, int]:
        return _make_mock_resumes(5), 5

    with patch("app.api.search._llm_endpoint_configured", return_value=True):
        with patch(
            "app.api.search.hh_client.search_resumes",
            new_callable=AsyncMock,
            side_effect=fake_search,
        ):
            r0 = client.post(
                "/api/v1/search",
                headers=auth_headers,
                json={"query": "Python", "page": 0, "per_page": 20},
            )
            assert r0.status_code == 200
            sid = r0.json().get("snapshot_id")
            assert sid

            with patch(
                "app.api.search.llm_evaluation.evaluate_all_resumes",
                new_callable=AsyncMock,
                side_effect=fake_eval,
            ):
                r1 = client.post(
                    f"/api/v1/search/{sid}/evaluate",
                    headers=auth_headers,
                    json={},
                )
                assert r1.status_code == 200
                data = r1.json()
                assert data["evaluated_count"] == 5
                for x in data["items"]:
                    assert set(x.keys()) == {"id", "llm_score"}
                    assert x.get("llm_score") == 77


def test_search_parse_requires_auth(client: TestClient) -> None:
    r = client.post("/api/v1/search/parse", json={"query": "Python Москва"})
    assert r.status_code in (401, 403)


def test_search_parse_returns_params(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/search/parse",
        headers=auth_headers,
        json={"query": "Python разработчик в Москве от 3 лет"},
    )
    assert r.status_code == 200
    data = r.json()
    assert "Python" in data["parsed_params"].get("skills", [])
    assert data["parsed_params"].get("region") == "Москва"
    assert "confidence" in data


def test_search_mock_hh_returns_candidates(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    r = client.post(
        "/api/v1/search",
        headers=auth_headers,
        json={"query": "Java developer", "page": 0, "per_page": 10},
    )
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["found"] >= 0
    assert "parsed_params" in data
    assert data.get("snapshot_id")
    assert "summary" not in data


def test_search_second_page_uses_snapshot_no_hh(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Вторая страница с snapshot_id не вызывает HH."""
    calls: list[int] = []

    async def fake_search(*args: object, **kwargs: object) -> tuple[list, int]:
        page = int(args[3]) if len(args) > 3 else 0
        per_page = int(args[4]) if len(args) > 4 else 50
        all_items = _make_mock_resumes(35)
        total = len(all_items)
        start = page * per_page
        chunk = all_items[start : start + per_page]
        calls.append(page)
        return chunk, total

    with patch(
        "app.api.search.hh_client.search_resumes",
        new_callable=AsyncMock,
        side_effect=fake_search,
    ):
        r1 = client.post(
            "/api/v1/search",
            headers=auth_headers,
            json={
                "query": "Python",
                "page": 0,
                "per_page": 20,
            },
        )
        assert r1.status_code == 200
        d1 = r1.json()
        sid = d1.get("snapshot_id")
        assert sid
        assert d1["found"] == 35
        assert len(d1["items"]) == 20
        assert len(calls) >= 1

        calls.clear()

        r2 = client.post(
            "/api/v1/search",
            headers=auth_headers,
            json={
                "query": "Python",
                "page": 1,
                "per_page": 20,
                "snapshot_id": sid,
            },
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2["snapshot_id"] == sid
        assert d2["page"] == 1
        assert len(d2["items"]) == 15
        assert d2["found"] == 35
        assert calls == []


def test_favorites_flow(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "mock-resume-e2e-1",
            "title_snapshot": "QA Title",
            "notes": "note",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r.status_code == 201
    fav_id = r.json()["id"]

    r2 = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "mock-resume-e2e-1",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r2.status_code == 409

    lst = client.get("/api/v1/favorites", headers=auth_headers)
    assert lst.status_code == 200
    assert len(lst.json()) >= 1

    patch = client.patch(
        f"/api/v1/favorites/{fav_id}/notes",
        headers=auth_headers,
        json={"notes": "updated"},
    )
    assert patch.status_code == 200
    assert patch.json()["notes"] == "updated"

    rm = client.delete(f"/api/v1/favorites/{fav_id}", headers=auth_headers)
    assert rm.status_code == 204
