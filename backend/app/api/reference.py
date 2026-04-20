from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.hh_access import ensure_hh_access_token
from app.config import settings
from app.models.user import User
from app.schemas.reference import (
    AreaItemOut,
    AreasListOut,
    ProfessionalRoleItemOut,
    ProfessionalRolesListOut,
)
from app.services import hh_areas, hh_client
from app.services.hh_client import HHClientError

router = APIRouter(prefix="/reference", tags=["reference"])


@router.get("/areas", response_model=AreasListOut)
async def list_areas_russia() -> AreasListOut:
    """Справочник регионов РФ из HeadHunter (публичный метод /areas, ветка id=113)."""
    try:
        rows = await hh_areas.get_russia_areas_cached()
    except httpx.HTTPError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Не удалось загрузить справочник регионов HeadHunter",
        ) from None
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Справочник регионов пуст или недоступен",
        )
    return AreasListOut(items=[AreaItemOut(**x) for x in rows])


@router.get("/professional-roles", response_model=ProfessionalRolesListOut)
async def list_professional_roles(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ProfessionalRolesListOut:
    """Справочник профессиональных ролей HH для фильтра в UI."""
    access = await ensure_hh_access_token(db, user.id)
    if not settings.feature_use_mock_hh and not access:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Подключите HeadHunter для загрузки справочника ролей",
        )
    try:
        reference, _ = await hh_client.get_professional_roles_reference(
            access,
            db=db,
            hh_token_user_id=user.id,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except HHClientError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.detail,
        ) from exc
    items = [
        ProfessionalRoleItemOut(id=rid, name=name)
        for rid, name in sorted(reference.id_to_name.items(), key=lambda it: it[1].lower())
    ]
    return ProfessionalRolesListOut(items=items)
