from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.config import Settings
from app.services import hh_client


@pytest.fixture
def real_hh_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Отключает mock HH и подставляет тестовые OAuth-поля."""
    from app.config import settings as live_settings

    patched = live_settings.model_copy(
        update={
            "feature_use_mock_hh": False,
            "hh_client_id": "test_client_id",
            "hh_client_secret": "test_secret",
            "hh_redirect_uri": "http://localhost:3000/settings",
        }
    )
    monkeypatch.setattr(hh_client, "settings", patched)
    return patched


@pytest.mark.asyncio
async def test_build_authorization_url_contains_client_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings as base

    monkeypatch.setattr(
        hh_client,
        "settings",
        base.model_copy(
            update={
                "hh_client_id": "oauth-test-client",
                "hh_redirect_uri": "http://localhost:3000/settings",
            }
        ),
    )
    url = hh_client.build_authorization_url("state-xyz")
    assert hh_client.HH_AUTH_URL in url
    assert "oauth-test-client" in url
    assert "state=state-xyz" in url.replace("%2D", "-")


@pytest.mark.asyncio
async def test_exchange_code_for_tokens_uses_http_when_not_mock(
    real_hh_settings: Settings,
) -> None:
    with respx.mock(assert_all_called=True) as router:
        router.post(hh_client.HH_TOKEN_URL).mock(
            return_value=Response(
                200,
                json={
                    "access_token": "atok",
                    "refresh_token": "rtok",
                    "expires_in": 3600,
                },
            )
        )
        data = await hh_client.exchange_code_for_tokens("auth-code-123")
    assert data["access_token"] == "atok"
    assert data["refresh_token"] == "rtok"


@pytest.mark.asyncio
async def test_search_resumes_requires_token_when_not_mock(
    real_hh_settings: Settings,
) -> None:
    with pytest.raises(PermissionError, match="HeadHunter is not connected"):
        await hh_client.search_resumes(
            None,
            {"skills": [], "text": "x"},
            None,
            0,
            20,
        )


@pytest.mark.asyncio
async def test_search_resumes_parses_hh_response(
    real_hh_settings: Settings,
) -> None:
    payload = {
        "found": 1,
        "items": [
            {
                "id": "resume-1",
                "title": "Python dev",
                "first_name": "Иван",
                "last_name": "Тестов",
                "age": 30,
                "area": {"name": "Москва"},
                "total_experience": {"months": 48},
                "skill_set": [{"name": "Python"}, {"name": "Django"}],
            }
        ],
    }
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{hh_client.HH_API}/resumes").mock(
            return_value=Response(200, json=payload)
        )
        items, found = await hh_client.search_resumes(
            "Bearer-token",
            {"skills": ["Python"], "text": "dev"},
            None,
            0,
            20,
        )
    assert found == 1
    assert len(items) == 1
    assert items[0]["title"] == "Python dev"
    assert items[0]["experience_years"] == 4
    assert "Python" in items[0]["skills"]
    assert items[0]["hh_resume_url"] == "https://hh.ru/resume/resume-1"
    assert "work_experience" not in items[0]


@pytest.mark.asyncio
async def test_fetch_resume_includes_work_experience(real_hh_settings: Settings) -> None:
    payload = {
        "id": "full-1",
        "title": "Engineer",
        "first_name": "Анна",
        "last_name": "Тест",
        "age": 31,
        "area": {"name": "Казань"},
        "total_experience": {"months": 36},
        "skill_set": [{"name": "Go"}],
        "skills": "<p>Обо мне: интересуюсь <strong>Java</strong> и системной разработкой.</p>",
        "education": {
            "level": {"name": "Высшее"},
            "primary": [
                {
                    "name": "Университет",
                    "organization": "Городской политех",
                    "result": "Информатика",
                    "year": 2010,
                    "education_level": {"name": "Бакалавр"},
                }
            ],
        },
        "experience": [
            {
                "start": "2021-01-01",
                "end": "2023-06-01",
                "company": "ACME",
                "position": "Разработчик",
                "description": "<p>Описание</p><br/>Вторая строка",
                "area": {"name": "Казань"},
            }
        ],
    }
    with respx.mock(assert_all_called=True) as router:
        router.get(f"{hh_client.HH_API}/resumes/full-1").mock(
            return_value=Response(200, json=payload)
        )
        row = await hh_client.fetch_resume("Bearer-token", "full-1")
    assert row["title"] == "Engineer"
    assert "work_experience" in row
    assert len(row["work_experience"]) == 1
    we = row["work_experience"][0]
    assert we["company"] == "ACME"
    assert we["position"] == "Разработчик"
    assert we["description"] and "Описание" in we["description"]
    assert "Вторая строка" in we["description"]
    assert row.get("about") and "Java" in row["about"]
    assert "education" in row and len(row["education"]) == 1
    assert "Информатика" in (row["education"][0].get("summary") or "")
