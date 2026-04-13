from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User


def _register_login_headers(client: TestClient, email: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123"},
    )
    assert r.status_code == 201, r.text
    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_delete_integration_editor_forbidden_non_super(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid.uuid4().hex[:10]
    mgr_email = f"mgr_{suffix}@revoke.test"
    victim_email = f"vic_{suffix}@revoke.test"

    _register_login_headers(client, mgr_email)
    victim_headers = _register_login_headers(client, victim_email)

    mgr = db_session.query(User).filter(User.email == mgr_email).one()
    mgr.is_admin = True
    victim = db_session.query(User).filter(User.email == victim_email).one()
    victim.can_edit_integration_settings = True
    db_session.commit()

    mgr_login = client.post(
        "/api/v1/auth/login",
        json={"email": mgr_email, "password": "testpass123"},
    )
    mgr_token = mgr_login.json()["access_token"]
    mgr_h = {"Authorization": f"Bearer {mgr_token}"}

    r = client.delete(
        f"/api/v1/admin/integration-settings-editors/{victim.id}",
        headers=mgr_h,
    )
    assert r.status_code == 403
    db_session.refresh(victim)
    assert victim.can_edit_integration_settings is True

    # супер не тот пользователь
    me = client.get("/api/v1/auth/me", headers=victim_headers)
    assert me.status_code == 200
    assert me.json().get("can_revoke_integration_editor_access") is False


def test_delete_integration_editor_super_success(
    client: TestClient,
    db_session: Session,
) -> None:
    super_email = f"super_{uuid.uuid4().hex[:10]}@revoke.test"
    victim_email = f"target_{uuid.uuid4().hex[:10]}@revoke.test"
    _register_login_headers(client, super_email)
    _register_login_headers(client, victim_email)

    super_user = db_session.query(User).filter(User.email == super_email).one()
    super_user.is_super_admin = True
    victim = db_session.query(User).filter(User.email == victim_email).one()
    victim.can_edit_integration_settings = True
    victim.is_admin = True
    db_session.commit()

    super_login = client.post(
        "/api/v1/auth/login",
        json={"email": super_email, "password": "testpass123"},
    )
    super_h = {"Authorization": f"Bearer {super_login.json()['access_token']}"}

    me = client.get("/api/v1/auth/me", headers=super_h)
    assert me.status_code == 200
    assert me.json().get("can_revoke_integration_editor_access") is True

    r = client.delete(
        f"/api/v1/admin/integration-settings-editors/{victim.id}",
        headers=super_h,
    )
    assert r.status_code == 204, r.text

    db_session.refresh(victim)
    assert victim.can_edit_integration_settings is False
    assert victim.is_admin is False


def test_delete_integration_editor_self_forbidden(
    client: TestClient,
    db_session: Session,
) -> None:
    super_email = f"self_{uuid.uuid4().hex[:10]}@revoke.test"
    _register_login_headers(client, super_email)
    super_user = db_session.query(User).filter(User.email == super_email).one()
    super_user.is_super_admin = True
    db_session.commit()

    super_login = client.post(
        "/api/v1/auth/login",
        json={"email": super_email, "password": "testpass123"},
    )
    super_h = {"Authorization": f"Bearer {super_login.json()['access_token']}"}

    r = client.delete(
        f"/api/v1/admin/integration-settings-editors/{super_user.id}",
        headers=super_h,
    )
    assert r.status_code == 403
