"""Поиск кандидатов из Telegram по локальным профилям."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.candidate_profile import CandidateProfile
from app.models.telegram_models import TelegramAccount, TelegramMessage, TelegramSource
from app.services.candidate_unified import candidate_profile_to_search_dict


def _tokens(q: str) -> list[str]:
    parts = re.split(r"\s+", (q or "").strip().lower())
    return [p for p in parts if len(p) >= 2]


def telegram_profile_owned_by_user(db: Session, cp: CandidateProfile, user_id: Any) -> bool:
    try:
        mid = uuid.UUID(str(cp.source_resume_id))
    except (ValueError, TypeError):
        return False
    m = db.get(TelegramMessage, mid)
    if not m:
        return False
    src = db.get(TelegramSource, m.source_id)
    if not src or not src.is_enabled:
        return False
    acc = db.get(TelegramAccount, src.account_id)
    return bool(acc and acc.owner_id == user_id)


def search_telegram_profiles(
    db: Session,
    user_id: Any,
    query_text: str,
    parsed: dict[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """
    Выборка candidate_profiles (telegram), доступных пользователю через его источники.
    """
    lim = max(1, min(int(limit), 2000))
    rows = list(
        db.scalars(
            select(CandidateProfile).where(CandidateProfile.source_type == "telegram")
        ).all()
    )
    rows = [r for r in rows if telegram_profile_owned_by_user(db, r, user_id)]

    text = (query_text or "").strip()
    tokens = _tokens(text)
    skills_req = [
        str(s).lower().strip()
        for s in (parsed.get("skills") or [])
        if str(s).strip()
    ]
    exp_min = parsed.get("experience_years_min")
    region = str(parsed.get("region") or "").lower().strip()

    def score_row(r: CandidateProfile) -> float:
        s = 0.0
        norm = r.normalized_payload if isinstance(r.normalized_payload, dict) else {}
        tg = norm.get("telegram") if isinstance(norm.get("telegram"), dict) else {}
        att_texts: list[str] = []
        for a in tg.get("attachments") or []:
            if not isinstance(a, dict):
                continue
            prev = a.get("extracted_preview")
            if isinstance(prev, str) and prev.strip():
                att_texts.append(prev.lower())
        about_norm = norm.get("about")
        about_extra = (about_norm or "").lower() if isinstance(about_norm, str) else ""
        att_blob = " ".join(att_texts)
        blob = " ".join(
            filter(
                None,
                [
                    (r.raw_text or "").lower(),
                    (r.full_name or "").lower(),
                    (r.title or "").lower(),
                    (r.area or "").lower(),
                    about_extra,
                    att_blob,
                ],
            )
        )
        for t in tokens:
            if t and t in blob:
                s += 2.0
        sk_list: list[str] = []
        if isinstance(r.skills, list):
            sk_list = [str(x).lower() for x in r.skills]
        elif isinstance(r.skills, dict):
            sk_list = [str(k).lower() for k in r.skills]
        blob_sk = " ".join(sk_list)
        for kw in skills_req:
            if kw in sk_list:
                s += 3.0
            elif kw in blob_sk:
                s += 1.0
        if exp_min is not None and r.experience_years is not None:
            if r.experience_years >= int(exp_min):
                s += 2.0
        if region and (r.area or "").lower().find(region) >= 0:
            s += 1.5
        return s

    if tokens or skills_req or region or exp_min is not None:
        rows.sort(key=score_row, reverse=True)
    else:
        rows.sort(key=lambda x: x.updated_at, reverse=True)

    return [candidate_profile_to_search_dict(r) for r in rows[:lim]]
