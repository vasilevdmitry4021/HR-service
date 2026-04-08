"""Преобразование единой модели кандидата в словарь для поиска и ИИ-оценки."""

from __future__ import annotations

import re
from typing import Any

from app.models.candidate_profile import CandidateProfile

_EXPERIENCE_START_FOR_TRIM = re.compile(
    r"(?im)^\s*(?:опыт\s+работы|трудовой\s+опыт|work\s+experience|employment\s+history)\b"
)


def _trim_legacy_telegram_about(about: str | None, work: Any) -> str | None:
    """У старых профилей в about мог попасть весь PDF — обрезаем до секции опыта."""
    if not about or not isinstance(about, str):
        return about
    we = work if isinstance(work, list) else []
    if len(we) < 2 or len(about) < 2000:
        return about
    m = _EXPERIENCE_START_FOR_TRIM.search(about)
    if m is not None and m.start() > 200:
        return about[: m.start()].strip()
    return about


def _skills_as_list(skills: Any) -> list[str]:
    if skills is None:
        return []
    if isinstance(skills, list):
        return [str(s).strip() for s in skills if str(s).strip()]
    if isinstance(skills, dict):
        return [str(k).strip() for k in skills if str(k).strip()]
    return []


def _contacts_from_profile(row: CandidateProfile) -> dict[str, Any]:
    base = row.contacts if isinstance(row.contacts, dict) else {}
    out: dict[str, Any] = {**base}
    emails: list[str] = []
    phones: list[str] = []
    tgs: list[str] = []
    try:
        rows = list(row.contact_rows)
    except Exception:
        rows = []
    for c in rows:
        if c.contact_type == "email":
            emails.append(c.contact_value)
        elif c.contact_type == "phone":
            phones.append(c.contact_value)
        elif c.contact_type == "telegram":
            tgs.append(c.contact_value)
    if emails:
        out.setdefault("emails", emails)
        out.setdefault("email", emails[0])
    if phones:
        out.setdefault("phones", phones)
        out.setdefault("phone", phones[0])
    if tgs:
        out.setdefault("telegram_handles", tgs)
        out.setdefault("telegram", tgs[0])
    return out


def _derive_parse_warnings(
    norm: dict[str, Any], parse_confidence: float | None
) -> list[str]:
    out: list[str] = []
    raw = norm.get("parse_warnings")
    if isinstance(raw, list):
        out.extend(str(x).strip() for x in raw if str(x).strip())
    elif isinstance(raw, str) and raw.strip():
        out.append(raw.strip())
    single = norm.get("parse_warning")
    if isinstance(single, str) and single.strip():
        out.append(single.strip())
    if parse_confidence is not None and parse_confidence < 0.5:
        out.append("Низкая уверенность автоматического разбора")
    return list(dict.fromkeys(out))


def _derive_incompleteness_flags(
    row: CandidateProfile, norm: dict[str, Any]
) -> list[str]:
    raw = norm.get("incompleteness_flags")
    if isinstance(raw, list) and raw:
        return list(
            dict.fromkeys(str(x).strip() for x in raw if str(x).strip())
        )
    flags: list[str] = []
    if not (row.full_name or "").strip():
        flags.append("Не указано имя")
    contacts = row.contacts if isinstance(row.contacts, dict) else {}
    has_email = bool(contacts.get("email") or contacts.get("emails"))
    has_phone = bool(contacts.get("phone") or contacts.get("phones"))
    has_tg = bool(contacts.get("telegram") or contacts.get("telegram_handles"))
    if not (has_email or has_phone or has_tg):
        flags.append("Не найдены контакты для связи")
    if row.experience_years is None:
        we = row.work_experience if isinstance(row.work_experience, list) else []
        if not we and not (
            isinstance(norm.get("work_experience"), list)
            and norm["work_experience"]
        ):
            flags.append("Не указан опыт работы")
    if row.title is None or not str(row.title).strip():
        flags.append("Не указана должность или заголовок")
    return flags


def _normalize_telegram_source_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Единый контракт для UI: source_display_name, message_link и др."""
    out = dict(d)
    sd = out.get("source_display_name")
    if not (isinstance(sd, str) and sd.strip()):
        for alt in ("display_name", "title", "name"):
            v = d.get(alt)
            if isinstance(v, str) and v.strip():
                out["source_display_name"] = v.strip()
                break
    return out


def _normalize_telegram_attachment_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Сведение имён полей вложений (ingestion / парсер / UI)."""
    out = dict(d)
    if out.get("filename") is None:
        n = d.get("name")
        if isinstance(n, str) and n.strip():
            out["filename"] = n.strip()
    if out.get("extracted_preview") is None:
        et = d.get("extracted_text")
        if isinstance(et, str):
            out["extracted_preview"] = et
    return out


def _telegram_sources_and_attachments(
    norm: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Источники и вложения Telegram в ответе поиска/карточки.

    Приоритет: блок ``normalized_payload.telegram`` (sources, attachments).
    Если списки там пусты или отсутствуют — читаем верхнеуровневые
    ``telegram_sources`` / ``telegram_attachments`` (устаревший дубль контракта).
    """
    sources: list[dict[str, Any]] = []
    attachments: list[dict[str, Any]] = []
    tg = norm.get("telegram")
    if isinstance(tg, dict):
        src = tg.get("sources")
        att = tg.get("attachments")
        if isinstance(src, list):
            sources.extend(x for x in src if isinstance(x, dict))
        if isinstance(att, list):
            attachments.extend(x for x in att if isinstance(x, dict))
    if not sources:
        top = norm.get("telegram_sources")
        if isinstance(top, list):
            sources.extend(x for x in top if isinstance(x, dict))
    if not attachments:
        topa = norm.get("telegram_attachments")
        if isinstance(topa, list):
            attachments.extend(x for x in topa if isinstance(x, dict))
    return (
        [_normalize_telegram_source_dict(x) for x in sources],
        [_normalize_telegram_attachment_dict(x) for x in attachments],
    )


def _source_links_as_list(row: CandidateProfile) -> list[dict[str, Any]]:
    try:
        links = list(row.source_links)
    except Exception:
        links = []
    return [
        {
            "source_type": sl.source_type,
            "source_id": sl.source_id,
            "source_url": sl.source_url,
        }
        for sl in links
    ]


def candidate_profile_to_search_dict(row: CandidateProfile) -> dict[str, Any]:
    """Формат строки снимка поиска для Telegram (совместим с CandidateOut + enrich)."""
    skills = _skills_as_list(row.skills)
    norm = row.normalized_payload if isinstance(row.normalized_payload, dict) else {}
    work = row.work_experience
    if work is None and isinstance(norm.get("work_experience"), list):
        work = norm["work_experience"]
    edu = row.education
    if edu is None and isinstance(norm.get("education"), list):
        edu = norm["education"]
    about = row.about
    if not about and isinstance(norm.get("about"), str):
        about = norm["about"]
    if not about and row.raw_text:
        about = (row.raw_text or "")[:4000]
    if row.source_type == "telegram":
        about = _trim_legacy_telegram_about(about, work)
    salary: dict[str, Any] | None = None
    if row.salary_amount is not None:
        salary = {
            "amount": row.salary_amount,
            "currency": row.salary_currency or "RUR",
        }
    pid = str(row.id)
    contacts = _contacts_from_profile(row)
    source_links = _source_links_as_list(row)
    norm_out = {
        **norm,
        "contacts": contacts,
        "candidate_source_links": source_links,
    }
    ts, ta = _telegram_sources_and_attachments(norm)
    parse_warnings = _derive_parse_warnings(norm, row.parse_confidence)
    incompleteness_flags = _derive_incompleteness_flags(row, norm)
    return {
        "id": pid,
        "hh_resume_id": "",
        "hh_resume_url": row.source_url,
        "source_type": "telegram",
        "candidate_profile_id": pid,
        "source_resume_id": row.source_resume_id,
        "title": row.title or "",
        "full_name": row.full_name or "",
        "age": norm.get("age") if isinstance(norm.get("age"), int) else None,
        "experience_years": row.experience_years,
        "salary": salary,
        "skills": skills,
        "area": row.area or "",
        "work_experience": work if isinstance(work, list) else [],
        "about": about if isinstance(about, str) else None,
        "education": edu if isinstance(edu, list) else [],
        "llm_score": None,
        "llm_analysis": None,
        "raw_text": row.raw_text or "",
        "normalized_payload": norm_out,
        "parse_confidence": row.parse_confidence,
        "parse_warnings": parse_warnings,
        "incompleteness_flags": incompleteness_flags,
        "telegram_sources": ts,
        "telegram_attachments": ta,
    }


def candidate_profile_to_export_norm(row: CandidateProfile) -> dict[str, Any]:
    """Нормализованный словарь для prepare_candidate_payload_for_export (Telegram)."""
    norm = row.normalized_payload if isinstance(row.normalized_payload, dict) else {}
    skills = _skills_as_list(row.skills)
    salary = None
    if row.salary_amount is not None:
        salary = {
            "amount": row.salary_amount,
            "currency": row.salary_currency or "RUR",
        }
    we = row.work_experience
    if we is None and isinstance(norm.get("work_experience"), list):
        we = norm["work_experience"]
    edu = row.education
    if edu is None and isinstance(norm.get("education"), list):
        edu = norm["education"]
    contacts = _contacts_from_profile(row)
    source_links = _source_links_as_list(row)
    return {
        **norm,
        "source_type": "telegram",
        "id": str(row.id),
        "hh_resume_id": str(row.id),
        "title": row.title,
        "full_name": row.full_name,
        "experience_years": row.experience_years,
        "area": row.area,
        "skills": skills,
        "education": edu,
        "work_experience": we,
        "contacts": contacts,
        "about": row.about or norm.get("about"),
        "salary": salary,
        "parse_confidence": row.parse_confidence,
        "candidate_source_links": source_links,
    }


def normalized_profile_for_llm(row: dict[str, Any]) -> dict[str, Any]:
    """Объединяет поля снимка в нормализованный вид для промптов и e-staff."""
    norm = row.get("normalized_payload")
    if not isinstance(norm, dict):
        norm = {}
    base = {
        "hh_resume_id": row.get("hh_resume_id") or row.get("id"),
        "id": row.get("id"),
        "title": row.get("title"),
        "full_name": row.get("full_name"),
        "experience_years": row.get("experience_years"),
        "area": row.get("area"),
        "skills": row.get("skills"),
        "salary": row.get("salary"),
        "about": row.get("about"),
        "education": row.get("education") or norm.get("education"),
        "work_experience": row.get("work_experience") or norm.get("work_experience"),
        "_raw": norm.get("_raw") if isinstance(norm.get("_raw"), dict) else {},
        "source_type": row.get("source_type", "hh"),
    }
    merged = {**norm, **{k: v for k, v in base.items() if v is not None}}
    if row.get("source_type") == "telegram":
        merged["source_type"] = "telegram"
        merged["_telegram_raw_text"] = row.get("raw_text") or ""
    return merged
