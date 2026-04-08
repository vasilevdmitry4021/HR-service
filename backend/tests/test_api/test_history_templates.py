from __future__ import annotations

from fastapi.testclient import TestClient


def test_history_after_search(client: TestClient, auth_headers: dict[str, str]) -> None:
    s = client.post(
        "/api/v1/search",
        headers=auth_headers,
        json={"query": "Go developer", "page": 0, "per_page": 5},
    )
    assert s.status_code == 200

    h = client.get("/api/v1/history", headers=auth_headers)
    assert h.status_code == 200
    data = h.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    assert "Go" in data["items"][0]["query"] or "go" in data["items"][0]["query"].lower()


def test_templates_crud(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.post(
        "/api/v1/templates",
        headers=auth_headers,
        json={"name": "Мой шаблон", "query": "Python Москва", "filters": None},
    )
    assert r.status_code == 201
    tid = r.json()["id"]

    lst = client.get("/api/v1/templates", headers=auth_headers)
    assert lst.status_code == 200
    assert any(t["id"] == tid for t in lst.json())

    upd = client.put(
        f"/api/v1/templates/{tid}",
        headers=auth_headers,
        json={"name": "Обновлённый", "query": "Python СПб", "filters": None},
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Обновлённый"

    rm = client.delete(f"/api/v1/templates/{tid}", headers=auth_headers)
    assert rm.status_code == 204
