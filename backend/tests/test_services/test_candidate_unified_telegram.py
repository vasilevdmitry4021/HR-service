"""Контракт единого словаря кандидата (Telegram): источники и вложения."""

from __future__ import annotations

import uuid

from app.models.candidate_profile import CandidateProfile
from app.services.candidate_unified import candidate_profile_to_search_dict


def _profile_with_norm(payload: dict) -> CandidateProfile:
    p = CandidateProfile(
        id=uuid.uuid4(),
        source_type="telegram",
        source_resume_id=str(uuid.uuid4()),
        source_url="https://t.me/c/123/456",
        full_name="Иван Тестов",
        title="Python-разработчик",
        area="Москва",
        experience_years=4,
        skills=["Python", "Django"],
        normalized_payload=payload,
        raw_text="Ищу работу Python",
        parse_confidence=0.9,
    )
    return p


def test_telegram_sources_nested_and_top_level_merge() -> None:
    nested = _profile_with_norm(
        {
            "telegram": {
                "sources": [
                    {
                        "display_name": "Канал IT",
                        "message_link": "https://t.me/x/1",
                    }
                ],
                "attachments": [],
            },
        }
    )
    d1 = candidate_profile_to_search_dict(nested)
    assert len(d1["telegram_sources"]) == 1
    assert d1["telegram_sources"][0].get("source_display_name") == "Канал IT"

    top_only = _profile_with_norm(
        {
            "telegram": {},
            "telegram_sources": [{"title": "Резервный заголовок", "message_link": "y"}],
            "telegram_attachments": [
                {"name": "cv.pdf", "extracted_text": "Java опыт 5 лет"}
            ],
        }
    )
    d2 = candidate_profile_to_search_dict(top_only)
    assert d2["telegram_sources"][0].get("source_display_name") == "Резервный заголовок"
    assert d2["telegram_attachments"][0].get("filename") == "cv.pdf"
    assert "Java" in (d2["telegram_attachments"][0].get("extracted_preview") or "")


def test_nested_sources_take_priority_over_top_level() -> None:
    p = _profile_with_norm(
        {
            "telegram": {
                "sources": [{"source_display_name": "Вложенный"}],
                "attachments": [],
            },
            "telegram_sources": [{"source_display_name": "Верхний", "message_link": "z"}],
        }
    )
    d = candidate_profile_to_search_dict(p)
    assert len(d["telegram_sources"]) == 1
    assert d["telegram_sources"][0]["source_display_name"] == "Вложенный"


def test_normalized_payload_includes_contacts_and_links() -> None:
    p = _profile_with_norm({"telegram": {"sources": [], "attachments": []}})
    d = candidate_profile_to_search_dict(p)
    np = d.get("normalized_payload")
    assert isinstance(np, dict)
    assert "contacts" in np
    assert "candidate_source_links" in np
