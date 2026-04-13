"""Интеграционные сценарии социального входа (мок провайдеров)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient


def _query_dict(url: str) -> dict[str, str]:
    q = parse_qs(urlparse(url).query)
    return {k: v[0] for k, v in q.items() if v}


def _fragment_dict(url: str) -> dict[str, str]:
    frag = urlparse(url).fragment or ""
    if not frag:
        return {}
    q = parse_qs(frag)
    return {k: v[0] for k, v in q.items() if v}


def _yandex_flow(client: TestClient, *, code: str) -> tuple[str, str]:
    r = client.get("/api/v1/auth/oauth/yandex/start", follow_redirects=False)
    assert r.status_code == 302, r.text
    loc = r.headers.get("location") or ""
    assert "oauth.yandex.ru" in loc
    state = _query_dict(loc).get("state") or ""
    assert state

    r2 = client.get(
        f"/api/v1/auth/oauth/yandex/callback?code={code}&state={state}",
        follow_redirects=False,
    )
    assert r2.status_code == 302, r.text
    fin = r2.headers.get("location") or ""
    assert "/auth/oauth/finish" in fin
    q = _fragment_dict(fin) or _query_dict(fin)
    assert "code" in q
    return q["code"], state


@pytest.mark.integration
def test_social_oauth_yandex_new_user_exchange(client: TestClient) -> None:
    code = "fixture_email:newuser_oauth@example.com"
    handoff, _ = _yandex_flow(client, code=code)

    r3 = client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r3.status_code == 200, r3.text
    data = r3.json()
    assert "access_token" in data and "refresh_token" in data

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "newuser_oauth@example.com"


@pytest.mark.integration
def test_social_oauth_strict_no_email_link_to_password_user(
    client: TestClient,
    unique_email: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings as app_settings
    from app.services import social_oauth_account as soa

    monkeypatch.setattr(
        soa,
        "settings",
        app_settings.model_copy(update={"social_oauth_strict_email_link": True}),
    )
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "testpass123"},
    )
    assert reg.status_code == 201
    password_user_id = reg.json()["id"]

    code = f"fixture_email:{unique_email}"
    handoff, _ = _yandex_flow(client, code=code)
    r3 = client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r3.status_code == 200, r3.text
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {r3.json()['access_token']}"},
    )
    assert me.json()["id"] != password_user_id
    assert me.json()["email"].endswith("@users.internal")


@pytest.mark.integration
def test_social_oauth_email_auto_link(client: TestClient, unique_email: str) -> None:
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "testpass123"},
    )
    assert reg.status_code == 201
    user_id = reg.json()["id"]

    code = f"fixture_email:{unique_email}"
    handoff, _ = _yandex_flow(client, code=code)

    r3 = client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r3.status_code == 200, r3.text
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {r3.json()['access_token']}"},
    )
    assert me.json()["id"] == user_id


@pytest.mark.integration
def test_social_oauth_repeat_provider_identity_same_user(client: TestClient) -> None:
    code = "fixture_email:repeat_identity@example.com"
    h1, _ = _yandex_flow(client, code=code)
    t1 = client.post("/api/v1/auth/oauth/exchange", json={"code": h1})
    assert t1.status_code == 200
    id1 = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {t1.json()['access_token']}"},
    ).json()["id"]

    h2, _ = _yandex_flow(client, code=code)
    t2 = client.post("/api/v1/auth/oauth/exchange", json={"code": h2})
    assert t2.status_code == 200
    id2 = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {t2.json()['access_token']}"},
    ).json()["id"]
    assert id1 == id2


@pytest.mark.integration
def test_social_oauth_handoff_reuse_fails(client: TestClient) -> None:
    handoff, _ = _yandex_flow(client, code="fixture_email:reuse_handoff@example.com")
    r_ok = client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r_ok.status_code == 200
    r_bad = client.post("/api/v1/auth/oauth/exchange", json={"code": handoff})
    assert r_bad.status_code == 401


@pytest.mark.integration
def test_social_oauth_handoff_invalid(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/oauth/exchange",
        json={"code": "not_a_valid_handoff_code_value_at_all_xx"},
    )
    assert r.status_code == 401


@pytest.mark.integration
def test_social_oauth_vk_start_redirect_has_pkce(client: TestClient) -> None:
    r = client.get("/api/v1/auth/oauth/vk/start", follow_redirects=False)
    assert r.status_code == 302
    loc = r.headers.get("location") or ""
    assert "id.vk.com" in loc or "vk.com" in loc
    q = _query_dict(loc)
    assert q.get("code_challenge_method") == "S256"
    assert q.get("code_challenge")
    assert q.get("state")
