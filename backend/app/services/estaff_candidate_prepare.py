"""Подготовка тела кандидата для e-staff (candidate/add) из единого нормализованного профиля (HH или Telegram)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

from app.config import settings
from app.services.hh_resume_contacts import contacts_from_hh_raw
from app.services.estaff_vocabulary import (
    get_vocabulary_items_cached,
    resolve_vocab_id,
)

logger = logging.getLogger(__name__)

FetchVocItems = Callable[[str], Awaitable[list[dict[str, Any]]]]


class EstaffMandatoryDataError(Exception):
    """Нет обязательного минимума полей для создания кандидата в e-staff."""

    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        super().__init__("; ".join(messages))


def hh_normalized_resume_to_estaff_payload(norm: dict[str, Any]) -> dict[str, Any]:
    """Базовые скалярные поля candidate из нормализованного резюме (без справочников и блоков)."""
    raw_any = norm.get("_raw")
    raw = raw_any if isinstance(raw_any, dict) else {}
    email, phone = contacts_from_hh_raw(raw)
    if settings.estaff_fio_placeholder_enabled:
        if not email:
            email = (
                (settings.estaff_contact_placeholder_email or "").strip()
                or "nocontact@placeholder.invalid"
            )
        if not phone:
            phone = (
                (settings.estaff_contact_placeholder_mobile or "").strip()
                or "+70000000000"
            )
    salary_val: int | float | None = None
    salary = norm.get("salary")
    if isinstance(salary, dict):
        amt = salary.get("amount")
        if isinstance(amt, (int, float)) and not isinstance(amt, bool):
            salary_val = amt
        elif isinstance(amt, str) and amt.strip():
            try:
                salary_val = int(amt.replace(" ", ""), 10)
            except ValueError:
                try:
                    salary_val = float(amt.replace(" ", "").replace(",", "."))
                except ValueError:
                    salary_val = None
    ln = str(raw.get("last_name") or "").strip()
    fn = str(raw.get("first_name") or "").strip()
    mn = str(raw.get("middle_name") or "").strip()
    if settings.estaff_fio_placeholder_enabled:
        if not fn:
            fn = (settings.estaff_fio_placeholder_firstname or "").strip() or "Имя не указано"
        if not ln:
            ln = (settings.estaff_fio_placeholder_lastname or "").strip() or "Фамилия не указана"
        pm = (settings.estaff_fio_placeholder_middlename or "").strip()
        if not mn and pm:
            mn = pm
    desired = str(norm.get("title") or "").strip() or None
    payload: dict[str, Any] = {
        "lastname": ln or None,
        "firstname": fn or None,
        "middlename": mn or None,
        "mobile_phone": phone,
        "email": email,
        "desired_position_name": desired,
        "salary": salary_val,
    }
    return {k: v for k, v in payload.items() if v not in (None, "", [], {})}


def _hh_period_to_year_month(val: Any) -> tuple[int | None, int | None]:
    if val is None:
        return None, None
    if isinstance(val, dict):
        y = val.get("year")
        m = val.get("month")
        try:
            yi = int(y) if y is not None else None
        except (TypeError, ValueError):
            yi = None
        try:
            mi = int(m) if m is not None else None
        except (TypeError, ValueError):
            mi = None
        return yi, mi
    if isinstance(val, str) and val.strip():
        s = val.strip()[:10]
        parts = s.split("-")
        if len(parts) >= 1 and parts[0].isdigit():
            try:
                yi = int(parts[0])
            except ValueError:
                return None, None
            mi = None
            if len(parts) >= 2 and parts[1].isdigit():
                mi = int(parts[1])
            return yi, mi
    return None, None


def build_prev_jobs_from_hh_raw(raw: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    exp = raw.get("experience")
    if not isinstance(exp, list):
        return out
    for block in exp:
        if not isinstance(block, dict):
            continue
        company = str(block.get("company") or "").strip()
        if not company:
            emp = block.get("employer")
            if isinstance(emp, dict) and emp.get("name"):
                company = str(emp.get("name") or "").strip()
        position = str(block.get("position") or "").strip()
        area_name = ""
        ar = block.get("area")
        if isinstance(ar, dict):
            area_name = str(ar.get("name") or "").strip()
        sy, sm = _hh_period_to_year_month(block.get("start"))
        ey, em = _hh_period_to_year_month(block.get("end"))
        if sy is None:
            continue
        if sm is None:
            sm = 1
        desc = block.get("description")
        comment = None
        if isinstance(desc, str) and desc.strip():
            comment = re.sub(r"<[^>]+>", " ", desc)
            comment = " ".join(comment.split()).strip()[:4000] or None
        row: dict[str, Any] = {
            "start_year": sy,
            "start_month": sm,
            "org_name": company,
            "position_name": position or "—",
        }
        if ey is not None:
            row["end_year"] = ey
        if em is not None:
            row["end_month"] = em
        if area_name:
            row["org_location_name"] = area_name
        if comment:
            row["comment"] = comment
        out.append(row)
    return out


def build_prev_educations_from_norm(norm: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    edu = norm.get("education")
    if not isinstance(edu, list):
        return out
    for block in edu:
        if not isinstance(block, dict):
            continue
        org = str(block.get("organization") or "").strip()
        if not org:
            continue
        year_raw = block.get("year")
        end_year: int | None = None
        if year_raw is not None:
            try:
                end_year = int(str(year_raw).strip()[:4])
            except ValueError:
                end_year = None
        spec = str(block.get("speciality") or "").strip()
        level = str(block.get("level") or "").strip()
        row: dict[str, Any] = {
            "org_name": org,
            "end_year": end_year if end_year is not None else 0,
        }
        if spec:
            row["department_name"] = spec
            row["speciality_name"] = spec
        elif level:
            row["department_name"] = level
        out.append(row)
    return out


def map_gender_id_from_hh_raw(raw: dict[str, Any]) -> int | None:
    g = raw.get("gender")
    if isinstance(g, dict):
        gid = str(g.get("id") or "").lower()
        if gid == "male":
            return 0
        if gid == "female":
            return 1
    if isinstance(g, str):
        low = g.lower().strip()
        if low == "male":
            return 0
        if low == "female":
            return 1
    return None


def _synthetic_hh_raw_from_unified(norm: dict[str, Any]) -> dict[str, Any]:
    """Совместимый с HH вид _raw для профилей из Telegram (контакты, опыт)."""
    fn, ln, mn = "", "", ""
    full = str(norm.get("full_name") or "").strip()
    parts = full.split()
    if len(parts) >= 3:
        ln, fn, mn = parts[0], parts[1], " ".join(parts[2:])
    elif len(parts) == 2:
        fn, ln = parts[0], parts[1]
    elif len(parts) == 1:
        fn = parts[0]

    contact_list: list[dict[str, Any]] = []
    contacts = norm.get("contacts")
    if isinstance(contacts, dict):
        em = contacts.get("email")
        if isinstance(em, str) and em.strip():
            contact_list.append({"type": {"id": "email"}, "value": em.strip()})
        ph = contacts.get("phone")
        if isinstance(ph, str) and ph.strip():
            contact_list.append({"type": {"id": "cell"}, "value": ph.strip()})
        tg = contacts.get("telegram")
        if isinstance(tg, str) and tg.strip():
            contact_list.append({"type": {"id": "telegram"}, "value": tg.strip()})

    exp_out: list[dict[str, Any]] = []
    we = norm.get("work_experience")
    if isinstance(we, list):
        for block in we:
            if not isinstance(block, dict):
                continue
            company = str(block.get("company") or "").strip()
            position = str(block.get("position") or "").strip()
            desc = block.get("description")
            desc_s = str(desc).strip() if desc is not None else ""
            row: dict[str, Any] = {
                "company": company,
                "position": position,
                "start": block.get("start"),
                "end": block.get("end"),
            }
            if desc_s:
                row["description"] = desc_s
            ar = block.get("area")
            if isinstance(ar, str) and ar.strip():
                row["area"] = {"name": ar.strip()}
            exp_out.append(row)

    return {
        "first_name": fn,
        "last_name": ln,
        "middle_name": mn,
        "contact": contact_list,
        "experience": exp_out,
    }


def telegram_export_completeness_warnings(norm: dict[str, Any]) -> list[str]:
    """Неблокирующие предупреждения о неполном профиле (источник Telegram)."""
    if norm.get("source_type") != "telegram":
        return []
    out: list[str] = []
    full = str(norm.get("full_name") or "").strip()
    title = str(norm.get("title") or "").strip()
    contacts = norm.get("contacts") if isinstance(norm.get("contacts"), dict) else {}
    if not isinstance(contacts, dict):
        contacts = {}
    email = str(contacts.get("email") or "").strip()
    phone = str(contacts.get("phone") or "").strip()
    if not full:
        out.append("В профиле Telegram не указано ФИО.")
    if not title:
        out.append("В профиле Telegram не указана желаемая должность (заголовок).")
    if not email and not phone:
        out.append("В профиле Telegram не указаны email и телефон.")
    else:
        if not email:
            out.append("В профиле Telegram не указан email.")
        if not phone:
            out.append("В профиле Telegram не указан телефон.")
    we = norm.get("work_experience")
    if not isinstance(we, list) or len(we) == 0:
        out.append("В профиле Telegram нет блока опыта работы.")
    edu = norm.get("education")
    if not isinstance(edu, list) or len(edu) == 0:
        out.append("В профиле Telegram нет сведений об образовании.")
    return out


def mandatory_minimum_blockers_for_payload(payload: dict[str, Any]) -> list[str]:
    """
    Обязательный минимум для отправки в e-staff без выдуманных данных.
    При включённых подстановках ФИО/контактов в настройках проверка смягчается.
    """
    blockers: list[str] = []
    fn = str(payload.get("firstname") or "").strip()
    ln = str(payload.get("lastname") or "").strip()
    if not fn or not ln:
        blockers.append(
            "Не заполнены имя и фамилия; укажите их в профиле или включите подстановки e-staff.",
        )
    email = str(payload.get("email") or "").strip()
    phone = str(payload.get("mobile_phone") or "").strip()
    if not email and not phone:
        blockers.append(
            "Нет email и мобильного телефона; укажите контакты в профиле или включите подстановки e-staff.",
        )
    return blockers


def merge_telegram_norm_for_estaff(norm: dict[str, Any]) -> dict[str, Any]:
    """Дополняет norm полем _raw для e-staff, если профиль из Telegram."""
    n = dict(norm)
    if n.get("source_type") != "telegram":
        return n
    raw = n.get("_raw")
    if isinstance(raw, dict) and raw:
        return n
    n["_raw"] = _synthetic_hh_raw_from_unified(n)
    return n


# Псевдоним по плану унификации
candidate_profile_to_estaff_payload = hh_normalized_resume_to_estaff_payload


def infer_educ_type_id_from_norm(norm: dict[str, Any]) -> int | None:
    """1–4 по документации e-staff; эвристика по текстам уровня."""
    edu = norm.get("education")
    if not isinstance(edu, list) or not edu:
        return None
    blob = json.dumps(edu, ensure_ascii=False).lower()
    if "неокончен" in blob or "неоконч" in blob:
        return 3
    if "высше" in blob:
        return 4
    if "среднее специальн" in blob or "средне проф" in blob or "колледж" in blob:
        return 2
    if "средн" in blob:
        return 1
    return None


async def prepare_candidate_payload_for_export(
    norm: dict[str, Any],
    *,
    server_name: str,
    api_token: str,
    fetch_voc_items: FetchVocItems,
    candidate_export_key: str,
) -> tuple[dict[str, Any], list[str]]:
    """
    Полное тело candidate (без user_login — его добавляет HTTP-клиент).
    Возвращает (payload, предупреждения подготовки).
    candidate_export_key — устойчивый внешний ключ для inet_uid (UUID профиля или id резюме HH).
    """
    warnings: list[str] = []
    norm = merge_telegram_norm_for_estaff(norm)
    if norm.get("source_type") == "telegram":
        warnings.extend(telegram_export_completeness_warnings(norm))
        pc = norm.get("parse_confidence")
        if isinstance(pc, (int, float)) and float(pc) < 0.5:
            warnings.append(
                "Данные из Telegram распознаны с низкой уверенностью; проверьте поля перед выгрузкой.",
            )
    base = hh_normalized_resume_to_estaff_payload(norm)
    payload = dict(base)

    ek = str(candidate_export_key or "").strip()
    if ek:
        payload["inet_uid"] = ek

    exp_y = norm.get("experience_years")
    if isinstance(exp_y, (int, float)) and not isinstance(exp_y, bool):
        payload["exp_years"] = int(exp_y)

    area = norm.get("area")
    if isinstance(area, str) and area.strip():
        payload["city_name"] = area.strip()

    raw = norm.get("_raw") if isinstance(norm.get("_raw"), dict) else {}

    gid = map_gender_id_from_hh_raw(raw)
    if gid is not None:
        payload["gender_id"] = gid

    et = infer_educ_type_id_from_norm(norm)
    if et is not None:
        payload["educ_type_id"] = et

    prev_edu = build_prev_educations_from_norm(norm)
    if prev_edu:
        payload["prev_educations"] = prev_edu

    prev_jobs = build_prev_jobs_from_hh_raw(raw)
    if prev_jobs:
        payload["prev_jobs"] = prev_jobs

    async def _voc_items(voc_id: str) -> list[dict[str, Any]]:
        return await get_vocabulary_items_cached(
            server_name,
            api_token,
            voc_id,
            fetch_voc_items,
        )

    area_name = area.strip() if isinstance(area, str) else ""
    if area_name:
        try:
            loc_items = await _voc_items("locations")
            res = resolve_vocab_id(
                loc_items,
                area_name,
                field_name="location_id",
                allow_prefix=True,
            )
            if res.id is not None:
                payload["location_id"] = res.id
            elif res.reason == "ambiguous":
                warnings.append(
                    f"Регион «{area_name}»: неоднозначное совпадение в справочнике locations",
                )
            elif res.reason == "not_found":
                warnings.append(
                    f"Регион «{area_name}»: нет точного совпадения в locations; оставлен только city_name",
                )
        except Exception as exc:
            logger.warning("estaff_prepare_locations_failed: %s", exc, exc_info=True)
            warnings.append("Справочник locations недоступен; region_id не заполнен")

    skills_list = norm.get("skills")
    if isinstance(skills_list, list) and skills_list:
        try:
            skill_items = await _voc_items("skill_types")
            mapped: list[dict[str, Any]] = []
            for s in skills_list[:20]:
                if not isinstance(s, str) or not s.strip():
                    continue
                label = s.strip()
                r = resolve_vocab_id(
                    skill_items,
                    label,
                    field_name="skills.type_id",
                    allow_prefix=False,
                )
                if r.id is not None:
                    mapped.append({"type_id": r.id, "comment": label})
                elif r.reason == "ambiguous":
                    warnings.append(f"Навык «{label}»: неоднозначное совпадение в skill_types")
                else:
                    warnings.append(f"Навык «{label}»: нет совпадения в skill_types")
            if mapped:
                payload["skills"] = mapped
        except Exception as exc:
            logger.warning("estaff_prepare_skills_failed: %s", exc, exc_info=True)
            warnings.append("Справочник skill_types недоступен; блок навыков не заполнен")

    blockers = mandatory_minimum_blockers_for_payload(payload)
    if blockers:
        raise EstaffMandatoryDataError(blockers)

    return payload, warnings
