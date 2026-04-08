from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.search_template import SearchTemplate
from app.models.user import User
from app.schemas.search_filters import ResumeSearchFilters
from app.schemas.templates import (
    SearchTemplateCreateIn,
    SearchTemplateOut,
    SearchTemplateUpdateIn,
)

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[SearchTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SearchTemplateOut]:
    rows = db.scalars(
        select(SearchTemplate)
        .where(SearchTemplate.user_id == user.id)
        .order_by(SearchTemplate.updated_at.desc())
    ).all()
    return [SearchTemplateOut.model_validate(r) for r in rows]


@router.post("", response_model=SearchTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: SearchTemplateCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SearchTemplateOut:
    filters_dump = (
        body.filters.model_dump(mode="json", exclude_none=True) if body.filters else None
    )
    row = SearchTemplate(
        user_id=user.id,
        name=body.name.strip(),
        query=body.query,
        filters=filters_dump,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return SearchTemplateOut.model_validate(row)


@router.put("/{template_id}", response_model=SearchTemplateOut)
def update_template(
    template_id: uuid.UUID,
    body: SearchTemplateUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SearchTemplateOut:
    row = db.get(SearchTemplate, template_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")

    patch = body.model_dump(exclude_unset=True)
    if "name" in patch and patch["name"] is not None:
        row.name = str(patch["name"]).strip()
    if "query" in patch and patch["query"] is not None:
        row.query = str(patch["query"])
    if "filters" in patch:
        fv = patch["filters"]
        if fv is None:
            row.filters = None
        else:
            row.filters = ResumeSearchFilters.model_validate(fv).model_dump(
                mode="json", exclude_none=True
            )

    db.commit()
    db.refresh(row)
    return SearchTemplateOut.model_validate(row)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    row = db.get(SearchTemplate, template_id)
    if not row or row.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    db.delete(row)
    db.commit()
