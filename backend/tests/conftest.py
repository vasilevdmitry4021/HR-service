"""Общие фикстуры: переменные окружения до импорта приложения и клиент API."""

from __future__ import annotations

import os
import pathlib
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

# Должно выполниться до первого import app.*
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://hr:hr@127.0.0.1:5432/hr_service_test",
    ),
)
os.environ.setdefault("SECRET_KEY", "pytest-secret-key-not-for-production")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "pytest-token-encryption-key-32bytes!!")
# Перекрываем значения из docker-compose / .env: выгрузка и HH в тестах без реального OAuth
os.environ["FEATURE_USE_MOCK_LLM"] = "true"
os.environ["FEATURE_USE_MOCK_HH"] = "true"
os.environ["FEATURE_USE_MOCK_SOCIAL_OAUTH"] = "true"
os.environ.setdefault("HR_PUBLIC_BASE_URL", "http://localhost:3000")
# Снимки поиска в тестах — в памяти процесса (не общий Redis из .env)
os.environ["REDIS_URL"] = ""
os.environ.setdefault("INTERNAL_LLM_ENDPOINT", "")
# Интеграционные тесты вызывают PUT глобальных настроек без роли администратора
os.environ.setdefault("SETTINGS_ADMIN_ONLY", "false")

from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402, F401 — регистрация ORM-моделей в Base.metadata
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    for item in items:
        raw = getattr(item, "path", None) or getattr(item, "fspath", None)
        path = pathlib.Path(str(raw))
        if "test_api" in path.parts:
            item.add_marker(pytest.mark.integration)


def _check_db() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL недоступен ({exc}). Запустите БД или задайте TEST_DATABASE_URL.")


@pytest.fixture(scope="session")
def _integration_db_ready() -> None:
    _check_db()
    Base.metadata.create_all(bind=engine)
    try:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("estaff_exports")}
        if "export_detail" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE estaff_exports "
                        "ADD COLUMN IF NOT EXISTS export_detail JSON"
                    )
                )
        user_cols = {c["name"] for c in insp.get_columns("users")}
        if "is_admin" not in user_cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
                    )
                )
        if "active_refresh_jti" not in user_cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN IF NOT EXISTS active_refresh_jti VARCHAR(64)"
                    )
                )
        if "can_edit_integration_settings" not in user_cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN IF NOT EXISTS can_edit_integration_settings "
                        "BOOLEAN NOT NULL DEFAULT false"
                    )
                )
        if "is_super_admin" not in user_cols:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN IF NOT EXISTS is_super_admin "
                        "BOOLEAN NOT NULL DEFAULT false"
                    )
                )
        fav_cols = {c["name"] for c in insp.get_columns("favorites")}
        if "llm_analysis" not in fav_cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE favorites ADD COLUMN IF NOT EXISTS llm_analysis JSONB")
                )
    except Exception:
        pass
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(_integration_db_ready: None) -> Session:
    session = SessionLocal()
    try:
        _truncate_tables(session)
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()


def _truncate_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE TABLE "
            "telegram_message_attachments, telegram_messages, telegram_sync_runs, "
            "telegram_sources, telegram_accounts, "
            "candidate_contacts, candidate_source_links, favorites, candidate_profiles, "
            "oauth_handoff_codes, oauth_identities, "
            "api_keys, estaff_exports, search_history, search_templates, system_settings, users "
            "RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture
def client(db_session: Session) -> TestClient:
    return TestClient(app)


@pytest.fixture
def unique_email() -> str:
    return f"user_{uuid.uuid4().hex[:12]}@example.com"


@pytest.fixture
def auth_headers(client: TestClient, unique_email: str) -> dict[str, str]:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "testpass123"},
    )
    assert r.status_code == 201, r.text
    r2 = client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "testpass123"},
    )
    assert r2.status_code == 200, r2.text
    token = r2.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
