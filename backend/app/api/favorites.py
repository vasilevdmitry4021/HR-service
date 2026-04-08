from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.favorite import Favorite
from app.models.user import User
from app.schemas.favorites import FavoriteCreateIn, FavoriteNotesPatch, FavoriteOut

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
        llm_score=body.llm_score,
        llm_summary=body.llm_summary,
        notes=body.notes or "",
    )
    db.add(row)
    db.commit()
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
