from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.hh_access import ensure_hh_access_token
from app.config import settings
from app.models.favorite import Favorite
from app.models.user import User
from app.schemas.favorites import (
    FavoriteCreateIn,
    FavoriteNotesPatch,
    FavoriteOut,
    FavoriteRefreshMeta,
    FavoriteRefreshOut,
)
from app.services import hh_client
from app.services.hh_client import HHClientError
from app.services.hh_resume_contacts import contacts_from_hh_raw

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("", response_model=list[FavoriteOut])
def list_favorites(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FavoriteOut]:
    rows = db.scalars(
        select(Favorite)
        .where(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
    ).all()
    return [FavoriteOut.model_validate(r) for r in rows]


@router.post("", response_model=FavoriteOut, status_code=status.HTTP_201_CREATED)
def add_favorite(
    body: FavoriteCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FavoriteOut:
    if body.candidate_profile_id is not None:
        existing = db.scalar(
            select(Favorite).where(
                Favorite.user_id == user.id,
                Favorite.candidate_id == body.candidate_profile_id,
            )
        )
    else:
        rid = (body.hh_resume_id or "").strip()
        existing = db.scalar(
            select(Favorite).where(
                Favorite.user_id == user.id,
                Favorite.hh_resume_id == rid,
            )
        )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Кандидат уже в избранном",
        )
    hh_rid = (body.hh_resume_id or "").strip() or None
    llm_score_val = body.llm_score
    llm_summary_val = body.llm_summary
    llm_analysis_json: dict | None = None
    if body.llm_analysis is not None:
        llm_analysis_json = body.llm_analysis.model_dump()
        llm_score_val = body.llm_analysis.llm_score
        raw_sum = body.llm_analysis.summary
        if isinstance(raw_sum, str):
            s = raw_sum.strip()
            llm_summary_val = s if s else None
        else:
            llm_summary_val = raw_sum

    row = Favorite(
        user_id=user.id,
        hh_resume_id=hh_rid,
        candidate_id=body.candidate_profile_id,
        title_snapshot=body.title_snapshot,
        full_name=body.full_name,
        area=body.area,
        skills_snapshot=body.skills_snapshot,
        experience_years=body.experience_years,
        age=body.age,
        salary_amount=body.salary_amount,
        salary_currency=body.salary_currency,
        llm_score=llm_score_val,
        llm_summary=llm_summary_val,
        llm_analysis=llm_analysis_json,
        notes=body.notes or "",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Кандидат уже в избранном",
        ) from None
    db.refresh(row)
    return FavoriteOut.model_validate(row)


@router.delete("/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(
    favorite_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = db.get(Favorite, favorite_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    db.delete(row)
    db.commit()


@router.patch("/{favorite_id}/notes", response_model=FavoriteOut)
def patch_favorite_notes(
    favorite_id: uuid.UUID,
    body: FavoriteNotesPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FavoriteOut:
    row = db.get(Favorite, favorite_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    row.notes = body.notes
    db.commit()
    db.refresh(row)
    return FavoriteOut.model_validate(row)


@router.post(
    "/{favorite_id}/refresh-from-hh",
    response_model=FavoriteRefreshOut,
)
async def refresh_favorite_from_hh(
    favorite_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FavoriteRefreshOut:
    row = db.get(Favorite, favorite_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")

    resume_id = (row.hh_resume_id or "").strip()
    if not resume_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя обновить с HeadHunter без идентификатора резюме HH",
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
        norm = await hh_client.fetch_resume(
            access,
            resume_id,
            keep_raw=True,
            db=db,
            hh_token_user_id=user.id,
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        ) from e
    except HHClientError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    raw_any = norm.get("_raw")
    raw = raw_any if isinstance(raw_any, dict) else {}
    new_email, new_phone = contacts_from_hh_raw(raw)

    norm_name = norm.get("full_name")
    norm_full = (
        norm_name.strip()
        if isinstance(norm_name, str) and norm_name.strip()
        else ""
    )

    full_name_updated = bool(norm_full)
    if norm_full:
        row.full_name = norm_full

    if new_email:
        row.contact_email = new_email
    if new_phone:
        row.contact_phone = new_phone

    contacts_unlocked = bool(new_email or new_phone)
    message: str | None = None
    if not contacts_unlocked:
        message = (
            "Контакты в ответе HeadHunter не получены. "
            "Проверьте доступ к контактам в кабинете работодателя на hh.ru."
        )

    db.commit()
    db.refresh(row)

    return FavoriteRefreshOut(
        favorite=FavoriteOut.model_validate(row),
        meta=FavoriteRefreshMeta(
            contacts_unlocked=contacts_unlocked,
            full_name_updated=full_name_updated,
            message=message,
        ),
    )
