from __future__ import annotations

import asyncio
import uuid
from time import sleep
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app.config import settings
from app.models.favorite import Favorite
from app.services import search_snapshot_cache
from app.services.hh_client import HHClientError


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
        *,
        user_id: uuid.UUID | None = None,
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
                assert data["coverage_ratio"] == 1.0
                assert data["llm_scored_count"] == 5
                assert data["fallback_scored_count"] == 0
                for x in data["items"]:
                    assert set(x.keys()) == {"id", "llm_score"}
                    assert x.get("llm_score") == 77


def test_evaluate_snapshot_progress_polling(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    async def fake_eval(
        access: str | None,
        resumes: list,
        parsed_params: dict,
        db: object,
        *,
        user_id: uuid.UUID | None = None,
        progress_callback=None,
    ):
        _ = access, parsed_params, db, user_id
        out: list[dict] = []
        for i, r in enumerate(resumes):
            d = dict(r)
            d["llm_score"] = 90 if i < 2 else 60
            out.append(d)
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "prescore",
                    "phase": "interactive",
                    "total_count": 2,
                    "llm_scored_count": 2,
                    "fallback_scored_count": 0,
                    "scores_delta": {str(out[0]["id"]): 90, str(out[1]["id"]): 90},
                }
            )
            progress_callback(
                {
                    "stage": "phase_done",
                    "phase": "interactive",
                    "phase_total_count": 2,
                    "phase_scored_count": 2,
                    "phase_llm_scored_count": 2,
                    "phase_fallback_count": 0,
                }
            )
            await asyncio.sleep(0.08)
            progress_callback(
                {
                    "stage": "prescore",
                    "phase": "background",
                    "total_count": 1,
                    "llm_scored_count": 2,
                    "fallback_scored_count": 1,
                    "scores_delta": {str(out[2]["id"]): 60},
                    "event": "fallback_done",
                }
            )
            progress_callback(
                {
                    "stage": "phase_done",
                    "phase": "background",
                    "phase_total_count": 1,
                    "phase_scored_count": 1,
                    "phase_llm_scored_count": 0,
                    "phase_fallback_count": 1,
                }
            )
        return out, {
            "llm_calls_total": 2,
            "interactive_scored_count": 2,
            "background_scored_count": 1,
            "llm_scored_count": 2,
            "fallback_scored_count": 1,
            "coverage_ratio": 1.0,
            "cache_hit": 0,
            "cache_miss": 0,
            "hh_fetch_count": 0,
        }

    async def fake_search(*args: object, **kwargs: object) -> tuple[list, int]:
        return _make_mock_resumes(3), 3

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
                rs = client.post(
                    f"/api/v1/search/{sid}/evaluate/start",
                    headers=auth_headers,
                    json={},
                )
                assert rs.status_code == 200, rs.text
                job_id = rs.json()["job_id"]
                assert job_id

                done = None
                observed_interactive_ready = False
                for _ in range(30):
                    sleep(0.02)
                    rp = client.get(
                        f"/api/v1/search/{sid}/evaluate/progress",
                        headers=auth_headers,
                        params={"job_id": job_id},
                    )
                    assert rp.status_code == 200, rp.text
                    payload = rp.json()
                    if (
                        payload["status"] == "running"
                        and payload["interactive_done_count"] >= 2
                    ):
                        observed_interactive_ready = True
                    if payload["status"] == "done":
                        done = payload
                        break

                assert done is not None
                assert observed_interactive_ready is True
                assert done["scored_count"] == 3
                assert done["llm_scored_count"] == 2
                assert done["fallback_scored_count"] == 1
                assert done["coverage_ratio"] == 1.0
                assert len(done["items"]) == 3
                assert done["interactive_total_count"] == 2
                assert done["background_total_count"] == 1
                assert done["interactive_done_count"] == 2
                assert done["background_done_count"] == 1
                assert done["interactive_llm_scored_count"] == 2
                assert done["background_fallback_count"] == 1
                assert all(item.get("llm_score") is not None for item in done["items"])
                assert done["metrics"]["cache_hit"] == 0
                assert done["metrics"]["cache_miss"] == 0
                assert done["metrics"]["hh_fetch_count"] == 0


def test_evaluate_snapshot_returns_hh_limit_error_detail(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> tuple[list, int]:
        return _make_mock_resumes(2), 2

    async def fake_eval(*args: object, **kwargs: object):
        raise HHClientError(403, "Превышен дневной лимит просмотров резюме")

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

    assert r1.status_code == 403
    assert r1.json()["detail"] == "Превышен дневной лимит просмотров резюме"


def test_evaluate_snapshot_progress_returns_hh_limit_error(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> tuple[list, int]:
        return _make_mock_resumes(3), 3

    async def fake_eval(*args: object, **kwargs: object):
        raise HHClientError(403, "Превышен дневной лимит просмотров резюме")

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
                rs = client.post(
                    f"/api/v1/search/{sid}/evaluate/start",
                    headers=auth_headers,
                    json={},
                )
                assert rs.status_code == 200, rs.text
                job_id = rs.json()["job_id"]
                assert job_id

                failed = None
                for _ in range(30):
                    sleep(0.02)
                    rp = client.get(
                        f"/api/v1/search/{sid}/evaluate/progress",
                        headers=auth_headers,
                        params={"job_id": job_id},
                    )
                    assert rp.status_code == 200, rp.text
                    payload = rp.json()
                    if payload["status"] == "error":
                        failed = payload
                        break

                assert failed is not None
                assert failed["stage"] == "error"
                assert (
                    failed["error"] == "Превышен дневной лимит просмотров резюме"
                )


def test_analyze_snapshot_progress_polling(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    async def fake_search(*args: object, **kwargs: object) -> tuple[list, int]:
        return _make_mock_resumes(4), 4

    async def fake_eval(
        access: str | None,
        resumes: list,
        parsed_params: dict,
        db: object,
        *,
        user_id: uuid.UUID | None = None,
        progress_callback=None,
    ):
        _ = access, parsed_params, db, user_id, progress_callback
        out: list[dict] = []
        for i, r in enumerate(resumes):
            d = dict(r)
            d["llm_score"] = 95 - i
            out.append(d)
        return out, {"coverage_ratio": 1.0}

    async def fake_analyze(
        access: str | None,
        items: list,
        parsed_params: dict,
        *,
        user_id: str,
        query: str,
        top_n: int,
        db: object,
        progress_callback=None,
    ):
        _ = access, parsed_params, user_id, query, db
        if progress_callback is not None:
            progress_callback(
                {"stage": "start", "processed_count": 0, "analyzed_count": 0}
            )
        out: list[dict] = []
        for i, row in enumerate(items):
            d = dict(row)
            if i < top_n:
                d["llm_analysis"] = {
                    "llm_score": d.get("llm_score"),
                    "is_relevant": True,
                    "strengths": ["Python"],
                    "gaps": [],
                    "summary": "ok",
                }
                if progress_callback is not None:
                    progress_callback(
                        {
                            "stage": "running",
                            "processed_count": i + 1,
                            "analyzed_count": i + 1,
                        }
                    )
            out.append(d)
        if progress_callback is not None:
            progress_callback(
                {"stage": "done", "processed_count": top_n, "analyzed_count": top_n}
            )
        return out

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
                reval = client.post(
                    f"/api/v1/search/{sid}/evaluate",
                    headers=auth_headers,
                    json={},
                )
                assert reval.status_code == 200, reval.text

            with patch(
                "app.api.search.llm_evaluation.analyze_top_resumes",
                new_callable=AsyncMock,
                side_effect=fake_analyze,
            ):
                rs = client.post(
                    f"/api/v1/search/{sid}/analyze/start",
                    headers=auth_headers,
                    json={"top_n": 2},
                )
                assert rs.status_code == 200, rs.text
                body = rs.json()
                assert body["status"] == "queued"
                assert body["total_count"] == 2
                job_id = body["job_id"]

                done = None
                for _ in range(30):
                    sleep(0.02)
                    rp = client.get(
                        f"/api/v1/search/{sid}/analyze/progress",
                        headers=auth_headers,
                        params={"job_id": job_id},
                    )
                    assert rp.status_code == 200, rp.text
                    payload = rp.json()
                    if payload["status"] == "done":
                        done = payload
                        break
                assert done is not None
                assert done["stage"] == "done"
                assert done["total_count"] == 2
                assert done["processed_count"] == 2
                assert done["analyzed_count"] == 2


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


def test_favorite_create_with_llm_analysis_json(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    payload = {
        "hh_resume_id": "hh-mock-099",
        "title_snapshot": "Dev",
        "notes": "",
        "llm_score": 50,
        "llm_summary": "старое",
        "llm_analysis": {
            "llm_score": 88,
            "is_relevant": True,
            "strengths": ["Python", "SQL"],
            "gaps": ["Нет опыта с X"],
            "summary": "Итог по кандидату",
        },
    }
    r = client.post("/api/v1/favorites", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["llm_score"] == 88
    assert body["llm_summary"] == "Итог по кандидату"
    assert body["llm_analysis"]["llm_score"] == 88
    assert body["llm_analysis"]["is_relevant"] is True
    assert body["llm_analysis"]["strengths"] == ["Python", "SQL"]
    assert body["llm_analysis"]["gaps"] == ["Нет опыта с X"]
    assert body["llm_analysis"]["summary"] == "Итог по кандидату"

    lst = client.get("/api/v1/favorites", headers=auth_headers)
    assert lst.status_code == 200
    found = next((x for x in lst.json() if x["id"] == body["id"]), None)
    assert found is not None
    assert found["llm_analysis"]["strengths"] == ["Python", "SQL"]


def test_get_candidate_without_q_uses_favorite_llm_analysis(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """GET кандидата без q: полный анализ из избранного, если JSON сохранён."""
    llm_analysis = {
        "llm_score": 72,
        "is_relevant": False,
        "strengths": ["Опыт"],
        "gaps": ["Разрыв"],
        "summary": "Краткая сводка",
    }
    fr = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-mock-001",
            "title_snapshot": "T",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
            "llm_analysis": llm_analysis,
        },
    )
    assert fr.status_code == 201, fr.text

    r = client.get("/api/v1/candidates/mock-1", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("llm_analysis") is not None
    la = data["llm_analysis"]
    assert la["llm_score"] == 72
    assert la["is_relevant"] is False
    assert la["strengths"] == ["Опыт"]
    assert la["gaps"] == ["Разрыв"]
    assert la["summary"] == "Краткая сводка"


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


async def _fake_resume_with_contacts(
    access: str | None,
    resume_id: str,
    *,
    keep_raw: bool = False,
) -> dict:
    return {
        "id": resume_id,
        "hh_resume_id": resume_id,
        "full_name": "Новое ФИО",
        "_raw": {
            "contact": [
                {"type": {"id": "email"}, "value": "new@example.com"},
                {"type": {"id": "cell"}, "value": "+79001112233"},
            ],
        },
    }


def test_refresh_favorite_from_hh_success(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-refresh-1",
            "title_snapshot": "Dev",
            "full_name": "Старое",
            "notes": "",
            "llm_score": 42,
            "llm_summary": "кратко",
        },
    )
    assert r.status_code == 201
    fav_id = r.json()["id"]

    with patch(
        "app.api.favorites.hh_client.fetch_resume",
        new_callable=AsyncMock,
        side_effect=_fake_resume_with_contacts,
    ):
        r2 = client.post(
            f"/api/v1/favorites/{fav_id}/refresh-from-hh",
            headers=auth_headers,
        )
    assert r2.status_code == 200
    body = r2.json()
    assert body["meta"]["contacts_unlocked"] is True
    assert body["meta"]["full_name_updated"] is True
    fav = body["favorite"]
    assert fav["full_name"] == "Новое ФИО"
    assert fav["contact_email"] == "new@example.com"
    assert fav["contact_phone"] == "+79001112233"
    assert fav["llm_score"] == 42
    assert fav["llm_summary"] == "кратко"


def test_refresh_favorite_from_hh_400_without_hh_resume_id(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session,
) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-will-clear",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r.status_code == 201
    fav_id = uuid.UUID(r.json()["id"])
    db_session.execute(
        update(Favorite).where(Favorite.id == fav_id).values(hh_resume_id=None)
    )
    db_session.commit()

    r2 = client.post(
        f"/api/v1/favorites/{fav_id}/refresh-from-hh",
        headers=auth_headers,
    )
    assert r2.status_code == 400


def test_refresh_favorite_from_hh_403_without_token(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-403",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r.status_code == 201
    fav_id = r.json()["id"]

    monkeypatch.setattr(settings, "feature_use_mock_hh", False)
    with patch(
        "app.api.favorites.ensure_hh_access_token",
        new_callable=AsyncMock,
        return_value=None,
    ):
        r2 = client.post(
            f"/api/v1/favorites/{fav_id}/refresh-from-hh",
            headers=auth_headers,
        )
    assert r2.status_code == 403


def test_refresh_favorite_merge_keeps_contacts_when_hh_empty(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session,
) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-merge-c",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r.status_code == 201
    fav_id = uuid.UUID(r.json()["id"])
    db_session.execute(
        update(Favorite)
        .where(Favorite.id == fav_id)
        .values(contact_email="kept@example.com", contact_phone="+79990000000")
    )
    db_session.commit()

    async def empty_contacts(*args: object, **kwargs: object) -> dict:
        return {
            "full_name": "Имя из HH",
            "_raw": {"contact": []},
        }

    with patch(
        "app.api.favorites.hh_client.fetch_resume",
        new_callable=AsyncMock,
        side_effect=empty_contacts,
    ):
        r2 = client.post(
            f"/api/v1/favorites/{fav_id}/refresh-from-hh",
            headers=auth_headers,
        )
    assert r2.status_code == 200
    fav = r2.json()["favorite"]
    assert fav["contact_email"] == "kept@example.com"
    assert fav["contact_phone"] == "+79990000000"
    assert fav["full_name"] == "Имя из HH"
    assert r2.json()["meta"]["contacts_unlocked"] is False


def test_refresh_favorite_merge_keeps_full_name_when_norm_empty(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-merge-n",
            "full_name": "Сохранённое ФИО",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r.status_code == 201
    fav_id = r.json()["id"]

    async def no_name(*args: object, **kwargs: object) -> dict:
        return {
            "full_name": "",
            "_raw": {},
        }

    with patch(
        "app.api.favorites.hh_client.fetch_resume",
        new_callable=AsyncMock,
        side_effect=no_name,
    ):
        r2 = client.post(
            f"/api/v1/favorites/{fav_id}/refresh-from-hh",
            headers=auth_headers,
        )
    assert r2.status_code == 200
    assert r2.json()["favorite"]["full_name"] == "Сохранённое ФИО"
    assert r2.json()["meta"]["full_name_updated"] is False


def test_refresh_favorite_404_not_found_or_foreign(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    rid = uuid.uuid4()
    r = client.post(
        f"/api/v1/favorites/{rid}/refresh-from-hh",
        headers=auth_headers,
    )
    assert r.status_code == 404


def test_refresh_favorite_hh_client_error(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    r = client.post(
        "/api/v1/favorites",
        headers=auth_headers,
        json={
            "hh_resume_id": "hh-err",
            "notes": "",
            "llm_score": None,
            "llm_summary": None,
        },
    )
    assert r.status_code == 201
    fav_id = r.json()["id"]

    async def boom(*args: object, **kwargs: object) -> None:
        raise HHClientError(502, "ошибка шлюза HH")

    with patch(
        "app.api.favorites.hh_client.fetch_resume",
        new_callable=AsyncMock,
        side_effect=boom,
    ):
        r2 = client.post(
            f"/api/v1/favorites/{fav_id}/refresh-from-hh",
            headers=auth_headers,
        )
    assert r2.status_code == 502
    assert "HH" in r2.json().get("detail", "") or "шлюз" in r2.json().get("detail", "")
