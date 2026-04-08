"""Пути к пакетам backend и telegram_ingestion, общая сессия БД для интеграционных тестов."""

from __future__ import annotations

import os
import pathlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

_TESTS_DIR = Path(__file__).resolve().parent
_INGEST_ROOT = _TESTS_DIR.parent
_REPO_ROOT = _INGEST_ROOT.parent
_BACKEND = _REPO_ROOT / "backend"

for _p in (_BACKEND, _INGEST_ROOT):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql://hr:hr@127.0.0.1:5432/hr_service_test",
    ),
)
os.environ.setdefault("SECRET_KEY", "pytest-secret-key-not-for-production")
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", "pytest-token-encryption-key-32bytes!!")

import app.models  # noqa: E402, F401
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    for item in items:
        raw = getattr(item, "path", None) or getattr(item, "fspath", None)
        path = pathlib.Path(str(raw))
        if path.name == "test_sync_sources.py":
            item.add_marker(pytest.mark.integration)


def _check_db() -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"PostgreSQL недоступен ({exc}). Запустите БД или задайте TEST_DATABASE_URL."
        )


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
    except Exception:
        pass
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session(_integration_db_ready: None) -> Session:
    session = SessionLocal()
    try:
        session.execute(
            text(
                "TRUNCATE TABLE "
                "telegram_message_attachments, telegram_messages, telegram_sync_runs, "
                "telegram_sources, telegram_accounts, "
                "candidate_contacts, candidate_source_links, favorites, candidate_profiles, "
                "api_keys, estaff_exports, search_history, search_templates, users "
                "RESTART IDENTITY CASCADE"
            )
        )
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()
