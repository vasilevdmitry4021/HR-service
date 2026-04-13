from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User


def test_register_login_me_refresh(client: TestClient, unique_email: str) -> None:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "longpassword1"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == unique_email

    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "longpassword1"},
    )
    assert r2.status_code == 200
    tokens = r2.json()
    assert "access_token" in tokens
    assert "refresh_token" in tokens

    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    me_body = me.json()
    assert me_body["email"] == unique_email
    assert me_body["is_super_admin"] is False
    assert me_body.get("can_revoke_integration_editor_access") is False

    r3 = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r3.status_code == 200
    assert r3.json()["access_token"]

    r4 = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r4.status_code == 401


def test_register_duplicate_conflict(client: TestClient, unique_email: str) -> None:
    payload = {"email": unique_email, "password": "longpassword1"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 201
    r = client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 409


def test_login_invalid_credentials(client: TestClient, unique_email: str) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "longpassword1"},
    )
    r = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "wrong-password"},
    )
    assert r.status_code == 401


def test_me_without_token_unauthorized(client: TestClient) -> None:
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 403 or r.status_code == 401


def test_me_returns_super_admin_flags(client: TestClient, db_session: Session, unique_email: str) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "longpassword1"},
    )
    user = db_session.query(User).filter(User.email == unique_email).one()
    user.is_super_admin = True
    db_session.commit()

    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "longpassword1"},
    )
    token = r2.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["is_super_admin"] is True
    assert body["can_revoke_integration_editor_access"] is True
