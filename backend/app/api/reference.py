from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException, status

from app.schemas.reference import AreaItemOut, AreasListOut
from app.services import hh_areas

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
