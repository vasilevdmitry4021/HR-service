from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.api import hh_access
from app.services.hh_client import HHClientError


class _ScalarResult:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def first(self) -> object | None:
        return self._row


class _FakeSession:
    def __init__(self, row: object | None) -> None:
        self._row = row
        self.commits = 0

    def scalars(self, _stmt: object) -> _ScalarResult:
        return _ScalarResult(self._row)

    def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_ensure_hh_access_token_force_refresh_does_not_return_stale_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(encrypted_key=b"encrypted")
    db = _FakeSession(row)
    user_id = uuid.uuid4()

    monkeypatch.setattr(
        hh_access,
        "settings",
        hh_access.settings.model_copy(
            update={
                "feature_use_mock_hh": False,
                "hh_client_id": "test-client",
                "hh_client_secret": "test-secret",
            }
        ),
    )
    monkeypatch.setattr(
        hh_access.encryption,
        "decrypt_json",
        lambda _blob: {
            "access_token": "stale-access-token",
            "refresh_token": "refresh-token",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "hh_user_id": "123",
            "employer_name": "Test employer",
        },
    )
    monkeypatch.setattr(
        hh_access,
        "resolve_hh_application_oauth",
        lambda _db: ("test-client", "test-secret", "http://localhost/callback"),
    )

    async def _fail_refresh(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise HHClientError(401, "token_expired")

    monkeypatch.setattr(hh_access, "refresh_access_token", _fail_refresh)

    token = await hh_access.ensure_hh_access_token(db, user_id, force_refresh=True)

    assert token is None
    assert db.commits == 0
