"""Извлечение полей кандидата из типовых фрагментов текста."""

from __future__ import annotations

from telegram_ingestion.services.candidate_extractor import (
    build_display_about,
    extract_candidate_fields,
)


def test_contacts_and_skills_from_plain_text() -> None:
    text = (
        "Иван Петров\n"
        "Python разработчик\n"
        "Почта ivan.petrov@mail.ru, тел. +7 (916) 111-22-33\n"
        "Навыки: Python, Django, Docker\n"
        "Опыт 4 года\n"
        "Зарплата от 200 000 руб.\n"
        "Город: Москва\n"
    )
    ext = extract_candidate_fields(text)
    assert ext.get("full_name") == "Иван Петров"
    contacts = ext.get("contacts") or {}
    assert "ivan.petrov@mail.ru" in (contacts.get("emails") or [])
    assert ext.get("experience_years") == 4
    assert ext.get("salary_amount") == 200_000
    assert any(s.lower() == "python" for s in (ext.get("skills") or []))


def test_work_experience_section_parsed() -> None:
    text = (
        "Кандидат\n\n"
        "Опыт работы:\n\n"
        "2019–2023\n"
        "ООО Альфа\n"
        "Инженер\n\n"
        "2023–н.в.\n"
        "ООО Бета\n"
        "Старший разработчик\n"
    )
    ext = extract_candidate_fields(text)
    work = ext.get("work_experience")
    assert isinstance(work, list)
    assert len(work) >= 1
    assert any("Альфа" in (e.get("company") or "") for e in work)


def test_education_section_parsed() -> None:
    text = (
        "ФИО\n\n"
        "Образование:\n"
        "МГУ, факультет ВМК, 2015\n"
        "Курс по машинному обучению, 2020\n"
    )
    ext = extract_candidate_fields(text)
    edu = ext.get("education")
    assert isinstance(edu, list)
    assert any("МГУ" in (e.get("institution") or e.get("raw") or "") for e in edu)


def test_normalized_payload_includes_sections() -> None:
    text = (
        "Имя\nОпыт работы:\nКомпания X\nДолжность Y\n\n"
        "Образование:\nУниверситет Z 2018\n"
    )
    ext = extract_candidate_fields(text)
    norm = ext.get("normalized_payload") or {}
    assert norm.get("work_experience") is not None
    assert norm.get("education") is not None


def test_english_section_headers() -> None:
    text = (
        "Jane Doe\nWork experience:\n\n"
        "2020–2022\nAcme Corp\nDeveloper\n\n"
        "Education:\nMIT 2019\n"
    )
    ext = extract_candidate_fields(text)
    assert ext.get("work_experience")
    assert ext.get("education")


def test_build_display_about_prefers_caption_over_attachment_resume() -> None:
    caption = (
        "Рекомендую #QA Lead\n\n"
        "Краткое описание кандидата из поста: специалист по тестированию, "
        "опыт во встраиваемых и веб-проектах, готов к удалённому формату.\n\n"
        "TG @user (Имя)"
    )
    pdf = (
        "Иван Иванов\n\n"
        "О себе Длинный текст из PDF.\n\n"
        "Опыт работы\n\n"
        "2020–2024 ООО Ромашка Инженер\n"
    )
    combined = caption + "\n\n[Вложение: cv.pdf]\n" + pdf
    short = build_display_about(
        message_caption=caption,
        full_combined_text=combined,
    )
    assert short is not None
    assert "Краткое описание" in short
    assert "Рекомендую" not in short
    assert "TG @" not in short
    assert "Опыт работы" not in short
    assert "Ромашка" not in short


def test_attachment_marker_stripped_and_professional_experience_section() -> None:
    pdf = (
        "[Вложение: Ilia Lopukhov Creative Director.pdf]\n"
        "Ilia Lopukhov\n"
        "Creative Director\n"
        "Indonesia, Bali\n\n"
        "**PROFESSIONAL EXPERIENCE\n"
        "Creative Director Oct 2020 - Jun 2025\n"
        "Realweb Digital Agency\n\n"
        "**EDUCATION**\n"
        "Tula State University, 2012\n"
    )
    ext = extract_candidate_fields(pdf, is_attachment_text=True)
    assert ext.get("full_name") == "Ilia Lopukhov"
    assert ext.get("title") == "Creative Director"
    assert "[Вложение" not in (ext.get("title") or "")
    work = ext.get("work_experience") or []
    assert isinstance(work, list)
    assert len(work) >= 1
    blob = " ".join(
        str(e.get("company") or "")
        + str(e.get("position") or "")
        + str(e.get("raw") or "")
        for e in work
    )
    assert "Realweb" in blob


def test_extract_candidate_fields_short_about_with_caption() -> None:
    cap = "Middle summary " * 8
    pdf = "Header\n\nОпыт работы\n\n2019 Corp Dev\n" * 3
    combined = cap + "\n\n" + pdf
    ext = extract_candidate_fields(combined, message_caption=cap)
    ab = ext.get("about") or (ext.get("normalized_payload") or {}).get("about")
    assert isinstance(ab, str)
    assert "Опыт работы" not in ab
    assert len(ab) < len(combined)
