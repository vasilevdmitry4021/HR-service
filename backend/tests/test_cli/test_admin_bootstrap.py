from __future__ import annotations

import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cli.admin_bootstrap import run
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User


def _session_factory() -> Session:
    return SessionLocal()


def test_create_super_admin_creates_and_is_idempotent(db_session: Session) -> None:
    out = io.StringIO()
    err = io.StringIO()
    email = "bootstrap_admin@example.com"

    code1 = run(
        [
            "create-super-admin",
            "--email",
            email,
            "--password",
            "bootstrap-pass-123",
        ],
        session_factory=_session_factory,
        stdout=out,
        stderr=err,
    )
    assert code1 == 0
    assert "Создан пользователь" in out.getvalue()

    db_session.expire_all()
    user = db_session.scalars(select(User).where(User.email == email)).one()
    assert user.is_super_admin is True
    assert user.password_hash

    out = io.StringIO()
    err = io.StringIO()
    code2 = run(
        [
            "create-super-admin",
            "--email",
            email,
            "--password",
            "bootstrap-pass-123",
        ],
        session_factory=_session_factory,
        stdout=out,
        stderr=err,
    )
    assert code2 == 0
    assert "Без изменений" in out.getvalue()


def test_grant_super_admin_requires_existing_user(db_session: Session) -> None:
    out = io.StringIO()
    err = io.StringIO()
    code = run(
        ["grant-super-admin", "--email", "missing@example.com"],
        session_factory=_session_factory,
        stdout=out,
        stderr=err,
    )
    assert code == 1
    assert "Пользователь не найден" in err.getvalue()


def test_grant_super_admin_updates_user(db_session: Session) -> None:
    email = "existing@example.com"
    db_session.add(User(email=email, password_hash=hash_password("grant-pass-123")))
    db_session.commit()

    out = io.StringIO()
    err = io.StringIO()
    code = run(
        ["grant-super-admin", "--email", email],
        session_factory=_session_factory,
        stdout=out,
        stderr=err,
    )
    assert code == 0
    assert "выдан" in out.getvalue().lower()

    db_session.expire_all()
    user = db_session.scalars(select(User).where(User.email == email)).one()
    assert user.is_super_admin is True


def test_revoke_super_admin_forbidden_for_last_one(db_session: Session) -> None:
    email = "solo@example.com"
    db_session.add(
        User(
            email=email,
            password_hash=hash_password("revoke-pass-123"),
            is_super_admin=True,
        )
    )
    db_session.commit()

    out = io.StringIO()
    err = io.StringIO()
    code = run(
        ["revoke-super-admin", "--email", email],
        session_factory=_session_factory,
        stdout=out,
        stderr=err,
    )
    assert code == 1
    assert "последнего супер-админа" in err.getvalue()


def test_revoke_super_admin_success(db_session: Session) -> None:
    first = User(
        email="first@example.com",
        password_hash=hash_password("revoke-pass-123"),
        is_super_admin=True,
    )
    second = User(
        email="second@example.com",
        password_hash=hash_password("revoke-pass-123"),
        is_super_admin=True,
    )
    db_session.add_all([first, second])
    db_session.commit()

    out = io.StringIO()
    err = io.StringIO()
    code = run(
        ["revoke-super-admin", "--email", second.email],
        session_factory=_session_factory,
        stdout=out,
        stderr=err,
    )
    assert code == 0
    assert "снят" in out.getvalue().lower()

    db_session.expire_all()
    updated = db_session.scalars(select(User).where(User.email == second.email)).one()
    assert updated.is_super_admin is False
