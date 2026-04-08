"""Извлечение полей кандидата из текста сообщения и вложений (эвристики)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from app.services.skill_synonyms import extract_skills_from_text

_EMAIL = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
)
_PHONE = re.compile(r"(\+?\d[\d\s\-()]{8,}\d)")
_EXP_YEARS_AFTER = re.compile(
    r"(?:опыт|experience)[^\d]{0,24}(\d{1,2})\s*(?:лет|год|years?|y\.?)",
    re.I,
)
_EXP_YEARS_BEFORE = re.compile(
    r"(\d{1,2})\s*(?:\+\s*)?(?:лет|год|years?)\s+(?:опыт|experience|of\s+experience)",
    re.I,
)
_SALARY = re.compile(
    r"(?:зарплат|salary|оклад)[^\d]{0,24}([\d\s]{4,12})(?:\s*(?:₽|руб\.?|rub|rur))?",
    re.I,
)
_CITY = re.compile(
    r"(?:город|location|проживаю|relocat|релокац)[^\n]{0,40}([A-ZА-ЯЁ][a-zа-яё\-]{2,30})",
    re.I,
)

_SECTION_WORK = re.compile(
    r"(?i)(?:опыт\s+работы|трудовой\s+опыт|work\s+experience|employment\s+history|professional\s+experience)\s*:?\s*$",
)
_SECTION_EDU = re.compile(
    r"(?i)(?:образование|учёба|education|academic\s+background)\s*:?\s*$",
)
_SECTION_STOP = re.compile(
    r"(?i)(?:опыт\s+работы|трудовой\s+опыт|work\s+experience|employment\s+history|professional\s+experience|"
    r"образование|учёба|education|academic\s+background|"
    r"навыки|skills|стек|stack|"
    r"контакты|contacts|о\s+себе|about|summary|резюме|cv|"
    r"project\s+work|проектная\s+деятельность|certificates?|сертификат|languages?|языки)\s*:?\s*$",
)
_YEAR_RANGE = re.compile(
    r"(?i)(\d{4})\s*[\-–—]\s*(\d{4}|н\.?в\.?|настоящее|текущ|present|current|now)",
)
_EXPERIENCE_START = re.compile(
    r"(?im)(?:^\s*\*+\s*(?:опыт\s+работы|трудовой\s+опыт|work\s+experience|employment\s+history|professional\s+experience)\b"
    r"|^\s*(?:опыт\s+работы|трудовой\s+опыт|work\s+experience|employment\s+history|professional\s+experience)\b)",
)
_RECOMMEND_LINE = re.compile(r"^\s*рекомендую\b", re.I)
_ATTACHMENT_MARKER_LINE = re.compile(r"^\s*\[Вложение:\s*[^\]]+\]\s*$", re.I)


def _strip_attachment_marker_lines(text: str) -> str:
    """Убирает служебные строки [Вложение: имя.pdf] из текста для парсинга полей."""
    out: list[str] = []
    for line in (text or "").splitlines():
        if _ATTACHMENT_MARKER_LINE.match(line.strip()):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _line_for_section_match(raw: str) -> str:
    """Нормализует строку заголовка секции (маркдаун **, # в начале)."""
    s = (raw or "").strip()
    s = re.sub(r"^#+\s*", "", s)
    s = re.sub(r"^\*+\s*", "", s)
    s = re.sub(r"\s*\*+\s*$", "", s)
    return s.strip()


def _collapse_horizontal_spaces(text: str) -> str:
    """Убирает типичные артефакты извлечения PDF (лишние пробелы в строке)."""
    lines: list[str] = []
    for line in (text or "").splitlines():
        lines.append(re.sub(r"[ \t]{2,}", " ", line).rstrip())
    return "\n".join(ln for ln in lines if ln).strip()


def build_display_about(
    *,
    message_caption: str,
    full_combined_text: str,
    max_len: int = 4000,
) -> str | None:
    """
    Текст для поля «О себе»: не дублировать весь текст резюме из вложения.

    Приоритет: очищенная подпись к сообщению; иначе — фрагмент до секции опыта работы.
    """
    cap = (message_caption or "").strip()
    full = (full_combined_text or "").strip()
    if not full and not cap:
        return None

    def _caption_body(c: str) -> str:
        lines_out: list[str] = []
        for line in c.splitlines():
            s = line.strip()
            if not s:
                if lines_out and lines_out[-1] != "":
                    lines_out.append("")
                continue
            if _RECOMMEND_LINE.match(s):
                continue
            low = s.lower()
            if low.startswith("tg ") and "@" in s and len(s) < 120:
                continue
            if re.match(r"^@\w{4,}\s*\(", s):
                continue
            lines_out.append(s)
        joined = "\n".join(lines_out).strip()
        return _collapse_horizontal_spaces(joined)

    ac = _caption_body(cap)
    if len(ac) >= 60:
        return ac[:max_len].rstrip() or None

    body = _collapse_horizontal_spaces(full)
    body = re.sub(r"\[Вложение:\s*[^\]]+\]\s*", "", body, flags=re.I)
    m = _EXPERIENCE_START.search(body)
    if m is not None and m.start() > 120:
        frag = body[: m.start()].strip()
        if len(frag) >= 40:
            return frag[:max_len].rstrip() or None

    if ac:
        return ac[:max_len].rstrip() or None
    if body:
        return body[: min(max_len, 1200)].rstrip() or None
    return None


def _find_section_lines(lines: list[str], header_re: re.Pattern[str]) -> tuple[int, int] | None:
    start = None
    for i, line in enumerate(lines):
        norm = _line_for_section_match(line)
        if norm and header_re.fullmatch(norm):
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        raw = lines[j]
        s = raw.strip()
        if not s:
            continue
        stop_norm = _line_for_section_match(raw)
        if stop_norm and _SECTION_STOP.fullmatch(stop_norm) and j > start:
            end = j
            break
    return start, end


def _parse_work_experience_block(body: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    chunks = [c.strip() for c in re.split(r"\n\s*\n", body) if c.strip()]
    if not chunks and body.strip():
        chunks = [body.strip()]
    for chunk in chunks[:25]:
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if not lines:
            continue
        period = None
        m = _YEAR_RANGE.search(chunk)
        if m:
            period = f"{m.group(1)}–{m.group(2)}"
        company = None
        position = None
        if len(lines) >= 2 and _YEAR_RANGE.search(lines[0]):
            period = lines[0]
            company = lines[1]
            position = lines[2] if len(lines) > 2 else None
        elif len(lines) >= 2:
            company = lines[0]
            position = lines[1]
        else:
            company = lines[0]
        entry: dict[str, Any] = {"raw": chunk[:2000]}
        if company:
            entry["company"] = company[:512]
        if position:
            entry["position"] = position[:512]
        if period:
            entry["period"] = str(period)[:128]
        out.append(entry)
    return out


def _parse_education_block(body: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in body.splitlines():
        s = line.strip()
        if not s or len(s) < 4:
            continue
        stop_norm = _line_for_section_match(s)
        if stop_norm and _SECTION_STOP.fullmatch(stop_norm):
            break
        year = None
        my = re.search(r"\b(19|20)\d{2}\b", s)
        if my:
            year = my.group(0)
        inst = re.sub(r"\b(19|20)\d{2}\b", "", s).strip(" ,—-")
        entry: dict[str, Any] = {"raw": s[:2000]}
        if inst:
            entry["institution"] = inst[:512]
        if year:
            entry["year"] = year
        out.append(entry)
        if len(out) >= 20:
            break
    return out


def _extract_work_and_education(text: str) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
    t = (text or "").strip()
    if not t:
        return None, None
    lines = t.splitlines()
    work: list[dict[str, Any]] | None = None
    edu: list[dict[str, Any]] | None = None
    span = _find_section_lines(lines, _SECTION_WORK)
    if span:
        start, end = span
        body = "\n".join(lines[start:end]).strip()
        if body:
            parsed = _parse_work_experience_block(body)
            if parsed:
                work = parsed
    span_e = _find_section_lines(lines, _SECTION_EDU)
    if span_e:
        start, end = span_e
        body = "\n".join(lines[start:end]).strip()
        if body:
            parsed = _parse_education_block(body)
            if parsed:
                edu = parsed
    return work, edu


def _clean_title(raw_title: str) -> str:
    cleaned = raw_title.strip()
    cleaned = re.sub(r"^Рекомендую\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r'^["\']|["\']$', "", cleaned)
    cleaned = re.sub(r"^#", "", cleaned)
    return cleaned.strip()


def _is_recommender_line(line: str) -> bool:
    """Проверяет, является ли строка подписью рекомендателя (не кандидата)."""
    s = line.strip()
    low = s.lower()
    if _RECOMMEND_LINE.match(s):
        return True
    if low.startswith("tg ") and "@" in s and len(s) < 120:
        return True
    if re.match(r"^@\w{4,}\s*\(", s):
        return True
    return False


def _skip_as_job_title(line: str) -> bool:
    """Не использовать как должность строки-заголовки секций резюме."""
    norm = _line_for_section_match(line)
    if not norm:
        return True
    low = norm.lower()
    if low in (
        "summary",
        "education",
        "skills",
        "languages",
        "certificates",
        "experience",
        "projects",
        "contact",
        "проекты",
        "образование",
        "навыки",
        "языки",
        "сертификаты",
        "контакты",
    ):
        return True
    if _SECTION_WORK.fullmatch(low) or _SECTION_EDU.fullmatch(low):
        return True
    return False


def extract_candidate_fields(
    text: str,
    *,
    telegram_meta: dict[str, Any] | None = None,
    message_caption: str | None = None,
    is_attachment_text: bool = False,
) -> dict[str, Any]:
    """
    Извлекает поля кандидата из текста.

    Args:
        text: Основной текст для парсинга (из вложения или сообщения)
        telegram_meta: Метаданные Telegram (источники, вложения)
        message_caption: Текст сообщения (подпись к вложению)
        is_attachment_text: True если text — из вложения (PDF/DOCX),
                           False если text — из сообщения Telegram
    """
    t = _strip_attachment_marker_lines((text or "").strip())
    emails = list(dict.fromkeys(_EMAIL.findall(t)))
    phones = [m.group(1).strip() for m in _PHONE.finditer(t)]
    phones = list(dict.fromkeys(phones))

    tg_handles: list[str] = []
    if is_attachment_text:
        tg_handles = re.findall(r"(?:@|t\.me/)([a-zA-Z][a-zA-Z0-9_]{4,})", t, re.I)
        tg_handles = list(dict.fromkeys(tg_handles))
    else:
        for line in t.splitlines():
            if _is_recommender_line(line):
                continue
            found = re.findall(r"(?:@|t\.me/)([a-zA-Z][a-zA-Z0-9_]{4,})", line, re.I)
            for h in found:
                if h not in tg_handles:
                    tg_handles.append(h)

    title = None
    name = None
    if is_attachment_text:
        head_lines = [ln.strip() for ln in t.splitlines() if ln.strip()][:12]
        if head_lines:
            first_ln = head_lines[0]
            if (
                3 < len(first_ln) < 80
                and "@" not in first_ln
                and not _EMAIL.search(first_ln)
                and not _ATTACHMENT_MARKER_LINE.match(first_ln)
            ):
                name = _clean_title(first_ln)
        for cand in head_lines[1:8]:
            if _is_recommender_line(cand) or _ATTACHMENT_MARKER_LINE.match(cand.strip()):
                continue
            if _EMAIL.search(cand) or "@" in cand:
                continue
            if _skip_as_job_title(cand):
                continue
            if not (4 < len(cand) < 120):
                continue
            ct = _clean_title(cand)
            if name and ct.lower() == (name or "").lower():
                continue
            title = ct
            break

    if title is None:
        for line in t.splitlines()[:12]:
            s = line.strip()
            if _is_recommender_line(s):
                continue
            if _ATTACHMENT_MARKER_LINE.match(s):
                continue
            if _skip_as_job_title(s):
                continue
            if 10 < len(s) < 120 and not _EMAIL.search(s):
                title = _clean_title(s)
                break
    from_skills = extract_skills_from_text(t)
    skills = sorted(from_skills, key=lambda x: x.lower())[:40]
    if name is None:
        for line in t.splitlines()[:5]:
            first = line.strip()
            if not first:
                continue
            if _is_recommender_line(first):
                continue
            if _ATTACHMENT_MARKER_LINE.match(first):
                continue
            if 3 < len(first) < 80 and "@" not in first:
                name = _clean_title(first)
                break

    experience_years = None
    m_exp = _EXP_YEARS_BEFORE.search(t)
    if m_exp:
        try:
            experience_years = min(int(m_exp.group(1)), 60)
        except ValueError:
            pass
    if experience_years is None:
        m_exp = _EXP_YEARS_AFTER.search(t)
        if m_exp:
            try:
                experience_years = min(int(m_exp.group(1)), 60)
            except ValueError:
                pass

    salary_amount = None
    salary_currency = None
    m_sal = _SALARY.search(t)
    if m_sal:
        raw = re.sub(r"\D", "", m_sal.group(1))
        if raw.isdigit():
            n = int(raw)
            frag = m_sal.group(0).lower()
            if "тыс" in frag or re.search(r"\b[kк]\b", frag):
                n *= 1000
            if 10_000 <= n <= 10_000_000:
                salary_amount = n
                salary_currency = "RUR"

    area = None
    m_city = _CITY.search(t)
    if m_city:
        area = m_city.group(1).strip()

    work_experience, education = _extract_work_and_education(t)

    contacts = {
        "emails": emails,
        "phones": phones,
        "telegram_handles": tg_handles,
        "email": emails[0] if emails else None,
        "phone": phones[0] if phones else None,
        "telegram": tg_handles[0] if tg_handles else None,
    }

    meta = telegram_meta if isinstance(telegram_meta, dict) else {}
    sources = meta.get("sources")
    if not isinstance(sources, list):
        sources = []
    cap = "" if message_caption is None else message_caption
    display_about = build_display_about(
        message_caption=cap,
        full_combined_text=t,
        max_len=4000,
    )
    about_for_norm = display_about if display_about else (t[:8000] if t else None)
    norm = {
        "source_type": "telegram",
        "full_name": name,
        "title": title,
        "skills": skills,
        "contacts": contacts,
        "about": about_for_norm,
        "experience_years": experience_years,
        "salary_amount": salary_amount,
        "salary_currency": salary_currency,
        "area": area,
        "education": education,
        "work_experience": work_experience,
        "telegram": {
            "sources": sources,
            "attachments": meta.get("attachments") or [],
        },
    }
    return {
        "full_name": name,
        "title": title,
        "skills": skills[:30],
        "contacts": contacts,
        "experience_years": experience_years,
        "salary_amount": salary_amount,
        "salary_currency": salary_currency,
        "area": area,
        "education": education,
        "work_experience": work_experience,
        "about": display_about,
        "raw_text": t,
        "normalized_payload": norm,
    }


def telegram_source_entry(
    *,
    source_id: str,
    source_display_name: str,
    source_link: str | None,
    telegram_message_id: int,
    message_link: str | None,
    published_at: datetime | None,
) -> dict[str, Any]:
    pub = None
    if published_at is not None:
        if published_at.tzinfo is None:
            pub = published_at.replace(tzinfo=timezone.utc)
        else:
            pub = published_at.astimezone(timezone.utc)
    return {
        "source_id": source_id,
        "source_display_name": source_display_name,
        "channel_or_chat_link": source_link,
        "telegram_message_id": telegram_message_id,
        "message_link": message_link,
        "published_at": pub.isoformat() if pub else None,
    }
