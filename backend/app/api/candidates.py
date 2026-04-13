from __future__ import annotations

import uuid as uuid_std

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_current_user, get_db
from app.api.hh_access import ensure_hh_access_token
from app.config import settings
from app.models.candidate_profile import CandidateProfile
from app.models.favorite import Favorite
from app.models.user import User
from app.schemas.search import (
    CandidateDetailOut,
    EducationItemOut,
    LLMAnalysisOut,
    WorkExperienceItemOut,
)
from app.services import hh_client
from app.services.candidate_unified import candidate_profile_to_search_dict
from app.services.telegram_search import telegram_profile_owned_by_user
from app.services import llm_client
from app.services import llm_analysis_cache
from app.services import llm_resume_analyzer
from app.services import nlp_service
from app.services import resume_pdf
from app.services.hh_client import HHClientError

router = APIRouter(prefix="/candidates", tags=["candidates"])


def _llm_analysis_from_favorite(fav: Favorite | None) -> LLMAnalysisOut | None:
    """Оценка ИИ из записи избранного (без привязки к поисковому запросу)."""
    if fav is None:
        return None
    blob = fav.llm_analysis
    if isinstance(blob, dict) and blob:
        try:
            out = LLMAnalysisOut.model_validate(blob)
        except Exception:
            out = None
        else:
            has_content = (
                out.llm_score is not None
                or out.is_relevant is not None
                or bool(out.strengths)
                or bool(out.gaps)
                or (isinstance(out.summary, str) and out.summary.strip())
            )
            if has_content:
                return out
    raw_summary = fav.llm_summary
    summary = raw_summary.strip() if isinstance(raw_summary, str) else None
    if summary == "":
        summary = None
    score = fav.llm_score
    if score is None and summary is None:
        return None
    return LLMAnalysisOut(
        llm_score=score,
        is_relevant=None,
        strengths=[],
        gaps=[],
        summary=summary,
    )


@router.get("/{resume_id}/pdf")
async def get_candidate_pdf(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    if not settings.feature_pdf_export:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Экспорт PDF отключён (FEATURE_PDF_EXPORT)",
        )
    access: str | None = None
    if not settings.feature_use_mock_hh:
        access = await ensure_hh_access_token(db, user.id)
        if not access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Подключите HeadHunter для экспорта резюме",
            )

    try:
        raw = await hh_client.fetch_resume(
            access,
            resume_id,
            db=db,
            hh_token_user_id=user.id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except HHClientError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    pdf_bytes = await run_in_threadpool(resume_pdf.resume_html_to_pdf_bytes, raw)
    safe_stub = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in resume_id
    ).strip("_") or "resume"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_stub[:72]}.pdf"',
        },
    )


@router.post("/{resume_id}/analyze", response_model=LLMAnalysisOut)
async def analyze_candidate_resume(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    search_query: str = Query(..., alias="q", min_length=1, max_length=4000),
) -> LLMAnalysisOut:
    if not settings.feature_llm_resume_analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Анализ резюме с помощью ИИ отключён",
        )
    try:
        uid = uuid_std.UUID(resume_id.strip())
    except ValueError:
        uid = None
    if uid is not None:
        prof = db.get(CandidateProfile, uid)
        if prof and prof.source_type == "telegram":
            if not telegram_profile_owned_by_user(db, prof, user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Нет доступа к этому кандидату",
                )
            stub = candidate_profile_to_search_dict(prof)
            q = search_query.strip()
            parsed, _, _ = nlp_service.parse_natural_query(q, db=db)
            analysis = llm_resume_analyzer.analyze_resume(parsed, stub, db=db)
            uid_s = str(user.id)
            llm_analysis_cache.store_for_resume_ids(
                uid_s, [str(prof.id)], q, analysis
            )
            return LLMAnalysisOut(**analysis)

    access: str | None = None
    if not settings.feature_use_mock_hh:
        access = await ensure_hh_access_token(db, user.id)
        if not access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Подключите HeadHunter для анализа резюме",
            )

    try:
        raw = await hh_client.fetch_resume(
            access,
            resume_id,
            db=db,
            hh_token_user_id=user.id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except HHClientError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    q = search_query.strip()
    parsed, _, _ = nlp_service.parse_natural_query(q, db=db)
    analysis = llm_resume_analyzer.analyze_resume(parsed, raw, db=db)

    uid = str(user.id)
    keys = llm_analysis_cache.resume_lookup_keys(raw)
    rid_path = resume_id.strip()
    if rid_path and rid_path not in keys:
        keys = [rid_path] + keys
    keys = list(dict.fromkeys(k for k in keys if str(k).strip()))
    if not keys and rid_path:
        keys = [rid_path]
    if keys:
        llm_analysis_cache.store_for_resume_ids(uid, keys, q, analysis)

    return LLMAnalysisOut(**analysis)


@router.get("/{resume_id}", response_model=CandidateDetailOut)
async def get_candidate(
    resume_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    search_query: str | None = Query(None, alias="q", max_length=4000),
) -> CandidateDetailOut:
    try:
        uid = uuid_std.UUID(resume_id.strip())
    except ValueError:
        uid = None
    if uid is not None:
        prof = db.get(CandidateProfile, uid)
        if prof and prof.source_type == "telegram":
            if not telegram_profile_owned_by_user(db, prof, user.id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Нет доступа к этому кандидату",
                )
            d = candidate_profile_to_search_dict(prof)
            fav = db.scalar(
                select(Favorite).where(
                    Favorite.user_id == user.id,
                    Favorite.candidate_id == prof.id,
                )
            )
            fav_id = str(fav.id) if fav else None
            fav_notes = fav.notes if fav else None
            llm_part: LLMAnalysisOut | None = None
            if llm_client.llm_connection_configured(db) and search_query and search_query.strip():
                cached = llm_analysis_cache.get_cached(
                    str(user.id), str(prof.id), search_query.strip()
                )
                if cached is not None:
                    llm_part = LLMAnalysisOut(**cached)
            if llm_part is None:
                llm_part = _llm_analysis_from_favorite(fav)
            we_raw = d.get("work_experience") or []
            work_out: list[WorkExperienceItemOut] = []
            if isinstance(we_raw, list):
                for item in we_raw:
                    if isinstance(item, dict):
                        try:
                            work_out.append(WorkExperienceItemOut(**item))
                        except Exception:
                            work_out.append(
                                WorkExperienceItemOut(
                                    company=str(item.get("company") or ""),
                                    position=str(item.get("position") or ""),
                                )
                            )
            ed_raw = d.get("education") or []
            education_out: list[EducationItemOut] = []
            if isinstance(ed_raw, list):
                for item in ed_raw:
                    if isinstance(item, dict):
                        try:
                            education_out.append(EducationItemOut(**item))
                        except Exception:
                            education_out.append(
                                EducationItemOut(
                                    organization=str(
                                        item.get("organization") or ""
                                    ),
                                )
                            )
            about_out = d.get("about")
            if not isinstance(about_out, str):
                about_out = None
            elif not about_out.strip():
                about_out = None
            llm_score_out: int | None = None
            if llm_part is not None and isinstance(llm_part.llm_score, int):
                llm_score_out = llm_part.llm_score
            ts = d.get("telegram_sources")
            telegram_sources = (
                [x for x in ts if isinstance(x, dict)] if isinstance(ts, list) else []
            )
            ta = d.get("telegram_attachments")
            telegram_attachments = (
                [x for x in ta if isinstance(x, dict)] if isinstance(ta, list) else []
            )
            pw = d.get("parse_warnings")
            parse_warnings = (
                [str(x).strip() for x in pw if str(x).strip()]
                if isinstance(pw, list)
                else []
            )
            inc = d.get("incompleteness_flags")
            incompleteness_flags = (
                [str(x).strip() for x in inc if str(x).strip()]
                if isinstance(inc, list)
                else []
            )
            return CandidateDetailOut(
                id=str(prof.id),
                hh_resume_id="",
                hh_resume_url=d.get("hh_resume_url"),
                source_type="telegram",
                candidate_profile_id=str(prof.id),
                source_resume_id=prof.source_resume_id,
                title=str(d.get("title", "")),
                full_name=str(d.get("full_name", "")),
                age=d.get("age"),
                experience_years=d.get("experience_years"),
                salary=d.get("salary"),
                skills=list(d.get("skills") or []),
                area=str(d.get("area", "")),
                llm_score=llm_score_out,
                llm_analysis=llm_part,
                parse_confidence=d.get("parse_confidence"),
                parse_warnings=parse_warnings,
                incompleteness_flags=incompleteness_flags,
                telegram_sources=telegram_sources,
                telegram_attachments=telegram_attachments,
                favorite_id=fav_id,
                favorite_notes=fav_notes,
                work_experience=work_out,
                about=about_out,
                education=education_out,
                raw_message_text=prof.raw_text,
            )

    access: str | None = None
    if not settings.feature_use_mock_hh:
        access = await ensure_hh_access_token(db, user.id)
        if not access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Подключите HeadHunter для просмотра резюме",
            )

    try:
        raw = await hh_client.fetch_resume(
            access,
            resume_id,
            db=db,
            hh_token_user_id=user.id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e)) from e
    except HHClientError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    if search_query and search_query.strip():
        parsed, _, _ = nlp_service.parse_natural_query(
            search_query.strip(), db=db
        )
    else:
        parsed = {}

    llm_part: LLMAnalysisOut | None = None
    if llm_client.llm_connection_configured(db):
        cached: dict | None = None
        if search_query and search_query.strip():
            sq = search_query.strip()
            uid = str(user.id)
            for rid_try in (
                resume_id,
                str(raw.get("id", "")),
                str(raw.get("hh_resume_id", "")),
            ):
                rid_try = rid_try.strip()
                if not rid_try:
                    continue
                cached = llm_analysis_cache.get_cached(uid, rid_try, sq)
                if cached is not None:
                    break
        if cached is not None:
            llm_part = LLMAnalysisOut(**cached)

    fav = db.scalar(
        select(Favorite).where(
            Favorite.user_id == user.id,
            Favorite.hh_resume_id == raw.get("hh_resume_id", resume_id),
        )
    )
    fav_id = str(fav.id) if fav else None
    fav_notes = fav.notes if fav else None

    if llm_part is None:
        llm_part = _llm_analysis_from_favorite(fav)

    hh_url = raw.get("hh_resume_url")
    if hh_url is not None and not isinstance(hh_url, str):
        hh_url = str(hh_url) if hh_url else None
    if isinstance(hh_url, str):
        hh_url = hh_url.strip() or None

    we_raw = raw.get("work_experience") or []
    work_out: list[WorkExperienceItemOut] = []
    if isinstance(we_raw, list):
        for item in we_raw:
            if isinstance(item, dict):
                work_out.append(WorkExperienceItemOut(**item))

    ed_raw = raw.get("education") or []
    education_out: list[EducationItemOut] = []
    if isinstance(ed_raw, list):
        for item in ed_raw:
            if isinstance(item, dict):
                education_out.append(EducationItemOut(**item))

    about_val = raw.get("about")
    about_out = (
        str(about_val).strip()
        if isinstance(about_val, str) and about_val.strip()
        else None
    )

    llm_score_out: int | None = None
    if llm_part is not None and isinstance(llm_part.llm_score, int):
        llm_score_out = llm_part.llm_score

    return CandidateDetailOut(
        id=str(raw.get("id", "")),
        hh_resume_id=str(raw.get("hh_resume_id", "")),
        hh_resume_url=hh_url,
        title=str(raw.get("title", "")),
        full_name=str(raw.get("full_name", "")),
        age=raw.get("age"),
        experience_years=raw.get("experience_years"),
        salary=raw.get("salary"),
        skills=list(raw.get("skills") or []),
        area=str(raw.get("area", "")),
        llm_score=llm_score_out,
        llm_analysis=llm_part,
        favorite_id=fav_id,
        favorite_notes=fav_notes,
        work_experience=work_out,
        about=about_out,
        education=education_out,
    )
