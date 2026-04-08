from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.search_history import SearchHistory
from app.models.user import User
from app.schemas.history import SearchHistoryListOut, SearchHistoryOut

router = APIRouter(prefix="/history", tags=["history"])


@router.get("", response_model=SearchHistoryListOut)
def list_search_history(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SearchHistoryListOut:
    limit = min(max(limit, 1), 100)
    skip = max(skip, 0)

    total = db.scalar(
        select(func.count()).select_from(SearchHistory).where(SearchHistory.user_id == user.id)
    )
    total = int(total or 0)

    rows = db.scalars(
        select(SearchHistory)
        .where(SearchHistory.user_id == user.id)
        .order_by(SearchHistory.created_at.desc())
        .offset(skip)
        .limit(limit)
    ).all()

    return SearchHistoryListOut(
        items=[SearchHistoryOut.model_validate(r) for r in rows],
        total=total,
    )
