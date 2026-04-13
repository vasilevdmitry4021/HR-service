from __future__ import annotations

import html
import re
import time
import uuid
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.config import settings
from app.schemas.search_filters import ResumeSearchFilters
from app.services import mock_hh
from app.services.hh_errors import classify_hh_http_status
from app.services.hh_filter_mapper import flatten_params_for_httpx, merge_resume_search_params

HH_AUTH_URL = "https://hh.ru/oauth/authorize"
HH_TOKEN_URL = "https://hh.ru/oauth/token"
HH_API = "https://api.hh.ru"

USER_AGENT = "HR-Service/1.0 (dmitriy.vasiliev@krit.pro)"


class HHClientError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def build_authorization_url(
    state: str,
    *,
    client_id: str | None = None,
    redirect_uri: str | None = None,
) -> str:
    cid = settings.hh_client_id if client_id is None else client_id
    rid = settings.hh_redirect_uri if redirect_uri is None else redirect_uri
    params = {
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": rid,
        "state": state,
    }
    return f"{HH_AUTH_URL}?{urlencode(params)}"


def _hh_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": USER_AGENT,
    }


def _html_to_plain(text: Any) -> str | None:
    if text is None or not isinstance(text, str):
        return None
    s = text.strip()
    if not s:
        return None
    t = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    t = re.sub(r"</p\s*>", "\n\n", t, flags=re.I)
    t = re.sub(r"<li\s*>", "\n• ", t, flags=re.I)
    t = re.sub(r"</li\s*>", "", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t or None


def _hh_date_label(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, str) and val.strip():
        s = val.strip()[:10]
        parts = s.split("-")
        if len(parts) >= 2 and parts[0].isdigit():
            y, m = parts[0], parts[1]
            return f"{m}.{y}"
        return s
    if isinstance(val, dict):
        y = val.get("year")
        m = val.get("month")
        if y is not None and m is not None:
            return f"{int(m):02d}.{int(y)}"
        if y is not None:
            return str(y)
    return None


def _normalize_work_experience(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for exp in raw:
        if not isinstance(exp, dict):
            continue
        company = str(exp.get("company") or "").strip()
        if not company:
            emp = exp.get("employer")
            if isinstance(emp, dict) and emp.get("name"):
                company = str(emp.get("name") or "").strip()
        position = str(exp.get("position") or "").strip()
        area_name = ""
        ar = exp.get("area")
        if isinstance(ar, dict):
            area_name = str(ar.get("name") or "").strip()
        start_l = _hh_date_label(exp.get("start"))
        end_l = _hh_date_label(exp.get("end"))
        period = None
        if start_l or end_l:
            period = f"{start_l or '…'} — {end_l or 'настоящее время'}"
        desc = _html_to_plain(exp.get("description"))
        industry_parts: list[str] = []
        ind_one = exp.get("industry")
        if isinstance(ind_one, dict) and ind_one.get("name"):
            industry_parts.append(str(ind_one["name"]))
        inds = exp.get("industries")
        if isinstance(inds, list):
            for it in inds:
                if isinstance(it, dict) and it.get("name"):
                    industry_parts.append(str(it["name"]))
        industry_label = ", ".join(industry_parts) if industry_parts else None
        out.append(
            {
                "company": company,
                "position": position,
                "start": start_l,
                "end": end_l,
                "period_label": period,
                "area": area_name or None,
                "industry": industry_label,
                "description": desc,
            }
        )
    return out


def _normalize_education(raw: Any) -> list[dict[str, Any]]:
    """Блок education из ответа api.hh.ru (primary / additional / …)."""
    if not isinstance(raw, dict):
        return []
    top_level = raw.get("level")
    top_level_name = ""
    if isinstance(top_level, dict):
        top_level_name = str(top_level.get("name") or "").strip()
    out: list[dict[str, Any]] = []
    for key in ("primary", "additional", "attestation", "elementary"):
        block = raw.get(key)
        if not isinstance(block, list):
            continue
        for ed in block:
            if not isinstance(ed, dict):
                continue
            org = str(ed.get("organization") or ed.get("name") or "").strip()
            spec = str(ed.get("result") or "").strip()
            year = ed.get("year")
            year_str = str(year) if year is not None else None
            el = ed.get("education_level") or ed.get("level")
            level_name = ""
            if isinstance(el, dict):
                level_name = str(el.get("name") or "").strip()
            elif isinstance(el, str):
                level_name = el.strip()
            if not level_name and top_level_name:
                level_name = top_level_name
            parts: list[str] = []
            for p in (level_name, org, spec, year_str):
                if p:
                    parts.append(p)
            summary = " · ".join(parts) if parts else None
            if not summary and not org:
                continue
            out.append(
                {
                    "level": level_name or None,
                    "organization": org or None,
                    "speciality": spec or None,
                    "year": year_str,
                    "summary": summary,
                }
            )
    return out


def _about_from_resume_raw(it: dict[str, Any]) -> str | None:
    """
    Текст «О себе» / доп. сведения: в API HH это строка skills (HTML),
    не путать со списком skill_set, который мы кладём в нормализованное поле skills.
    """
    val = it.get("skills")
    if isinstance(val, str) and val.strip():
        return _html_to_plain(val)
    return None


def _resume_hh_url(it: dict[str, Any], resume_id: str) -> str | None:
    """Ссылка на страницу резюме на сайте HH (из API или по идентификатору)."""
    alt = it.get("alternate_url")
    if isinstance(alt, str):
        u = alt.strip()
        if u.startswith("https://") or u.startswith("http://"):
            return u
    rid = resume_id.strip()
    if rid:
        return f"https://hh.ru/resume/{rid}"
    return None


def _normalize_resume_item(
    it: dict[str, Any],
    *,
    include_work_experience: bool = False,
) -> dict[str, Any]:
    area_name = ""
    a = it.get("area")
    if isinstance(a, dict):
        area_name = str(a.get("name") or "")
    elif a:
        area_name = str(a)

    exp_years = 0
    te = it.get("total_experience")
    if isinstance(te, dict) and te.get("months") is not None:
        exp_years = int(te["months"]) // 12

    skills: list[str] = []
    skill_set = it.get("skill_set")
    if isinstance(skill_set, list):
        for s in skill_set:
            if isinstance(s, dict) and s.get("name"):
                skills.append(str(s["name"]))
            elif isinstance(s, str) and s.strip():
                skills.append(s.strip())

    fn = str(it.get("first_name") or "")
    ln = str(it.get("last_name") or "")
    full_name = (fn + " " + ln).strip()

    salary = it.get("salary")
    if salary is not None and not isinstance(salary, dict):
        salary = None

    rid = it.get("id")
    rid_str = str(rid) if rid is not None else ""
    result: dict[str, Any] = {
        "id": rid_str,
        "hh_resume_id": rid_str,
        "hh_resume_url": _resume_hh_url(it, rid_str),
        "title": str(it.get("title") or ""),
        "full_name": full_name,
        "age": it.get("age"),
        "experience_years": exp_years,
        "salary": salary,
        "skills": skills,
        "area": area_name,
        "_raw": it,
    }
    if include_work_experience:
        result["work_experience"] = _normalize_work_experience(it.get("experience"))
        about = _about_from_resume_raw(it)
        if about:
            result["about"] = about
        edu = _normalize_education(it.get("education"))
        if edu:
            result["education"] = edu
    return result


def _raise_if_hh_error(r: httpx.Response) -> None:
    if r.is_success:
        return
    code, msg = classify_hh_http_status(r)
    raise HHClientError(code, msg)


async def exchange_code_for_tokens(
    code: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    redirect_uri: str | None = None,
) -> dict[str, Any]:
    if settings.feature_use_mock_hh:
        await _sleep_short()
        return {
            "access_token": f"mock_access_{code[-8:]}",
            "refresh_token": f"mock_refresh_{int(time.time())}",
            "expires_in": 3600,
            "hh_user_id": "87654321",
            "employer_name": "ООО Тестовый работодатель",
        }

    cid = settings.hh_client_id if client_id is None else client_id
    csec = settings.hh_client_secret if client_secret is None else client_secret
    rid = settings.hh_redirect_uri if redirect_uri is None else redirect_uri

    async with httpx.AsyncClient() as client:
        r = await client.post(
            HH_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": cid,
                "client_secret": csec,
                "redirect_uri": rid,
                "code": code,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        _raise_if_hh_error(r)
        data = r.json()
    data.setdefault("hh_user_id", data.get("hh_user_id", ""))
    data.setdefault("employer_name", "")
    return data


async def refresh_access_token(
    refresh_token: str,
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> dict[str, Any]:
    if settings.feature_use_mock_hh:
        await _sleep_short()
        return {
            "access_token": f"mock_refreshed_{int(time.time())}",
            "refresh_token": refresh_token,
            "expires_in": 3600,
        }

    cid = settings.hh_client_id if client_id is None else client_id
    csec = settings.hh_client_secret if client_secret is None else client_secret
    if not cid or not csec:
        raise HHClientError(503, "HeadHunter OAuth не настроен для обновления токена")

    async with httpx.AsyncClient() as client:
        r = await client.post(
            HH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": cid,
                "client_secret": csec,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=30.0,
        )
        _raise_if_hh_error(r)
        data = r.json()
    if not isinstance(data, dict):
        raise HHClientError(503, "Некорректный ответ HeadHunter при обновлении токена")
    return data


async def fetch_employer_me(access_token: str) -> dict[str, Any]:
    if settings.feature_use_mock_hh:
        await _sleep_short()
        return {
            "id": "87654321",
            "name": "ООО Тестовый работодатель",
            "services": {"resume_database": True, "contacts_available": 150},
        }

    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HH_API}/me",
            headers=_hh_headers(access_token),
            timeout=30.0,
        )
        _raise_if_hh_error(r)
        return r.json()


async def _maybe_retry_hh_after_401(
    exc: HHClientError,
    access_token: str | None,
    db: Session | None,
    hh_token_user_id: uuid.UUID | None,
) -> str | None:
    if exc.status_code != 401 or settings.feature_use_mock_hh:
        return None
    if db is None or hh_token_user_id is None:
        return None
    from app.api import hh_access as _hh_access

    new_access = await _hh_access.ensure_hh_access_token(
        db, hh_token_user_id, force_refresh=True
    )
    if not new_access or new_access == access_token:
        return None
    return new_access


async def search_resumes(
    access_token: str | None,
    parsed: dict[str, Any],
    filters: ResumeSearchFilters | dict[str, Any] | None,
    page: int,
    per_page: int,
    *,
    db: Session | None = None,
    hh_token_user_id: uuid.UUID | None = None,
) -> tuple[list[dict[str, Any]], int]:
    merged = merge_resume_search_params(parsed, filters, page, per_page)

    if settings.feature_use_mock_hh:
        all_items = mock_hh.mock_resume_database()
        filtered = mock_hh.filter_resumes(all_items, parsed, filters, merged)
        total = len(filtered)
        start = page * per_page
        chunk = filtered[start : start + per_page]
        return chunk, total

    if not access_token:
        raise PermissionError("HeadHunter is not connected")

    flat = flatten_params_for_httpx(merged)
    token = access_token
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HH_API}/resumes",
            params=flat,
            headers=_hh_headers(token or ""),
            timeout=30.0,
        )
        try:
            _raise_if_hh_error(r)
        except HHClientError as e:
            retry_tok = await _maybe_retry_hh_after_401(e, token, db, hh_token_user_id)
            if retry_tok is None:
                raise
            token = retry_tok
            r = await client.get(
                f"{HH_API}/resumes",
                params=flat,
                headers=_hh_headers(token),
                timeout=30.0,
            )
            _raise_if_hh_error(r)
        data = r.json()

    items_raw = data.get("items", [])
    items: list[dict[str, Any]] = []
    for it in items_raw:
        if isinstance(it, dict):
            norm = _normalize_resume_item(it)
            norm.pop("_raw", None)
            items.append(norm)
    return items, int(data.get("found", len(items)))


async def fetch_resume(
    access_token: str | None,
    resume_id: str,
    *,
    keep_raw: bool = False,
    db: Session | None = None,
    hh_token_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if settings.feature_use_mock_hh:
        await _sleep_short()
        row = mock_hh.get_resume_by_id(resume_id)
        if not row:
            raise HHClientError(404, "Резюме не найдено")
        it = mock_hh.resume_dict_as_hh_api_resume(dict(row))
        norm = _normalize_resume_item(it, include_work_experience=True)
        if not keep_raw:
            norm.pop("_raw", None)
        return norm

    if not access_token:
        raise PermissionError("HeadHunter is not connected")

    token = access_token
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{HH_API}/resumes/{resume_id}",
            headers=_hh_headers(token),
            timeout=30.0,
        )
        try:
            _raise_if_hh_error(r)
        except HHClientError as e:
            retry_tok = await _maybe_retry_hh_after_401(e, token, db, hh_token_user_id)
            if retry_tok is None:
                raise
            token = retry_tok
            r = await client.get(
                f"{HH_API}/resumes/{resume_id}",
                headers=_hh_headers(token),
                timeout=30.0,
            )
            _raise_if_hh_error(r)
        it = r.json()
    if not isinstance(it, dict):
        raise HHClientError(503, "Некорректный ответ HeadHunter")
    norm = _normalize_resume_item(it, include_work_experience=True)
    if not keep_raw:
        norm.pop("_raw", None)
    return norm


async def _sleep_short() -> None:
    import asyncio

    await asyncio.sleep(0.05)
