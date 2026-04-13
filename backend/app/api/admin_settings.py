from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_integration_editors_manager, get_super_settings_admin
from app.models.user import User
from app.schemas.admin_settings import AddIntegrationEditorIn, IntegrationEditorOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/integration-settings-editors",
    response_model=list[IntegrationEditorOut],
)
def list_integration_settings_editors(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_integration_editors_manager),
) -> list[IntegrationEditorOut]:
    rows = db.scalars(
        select(User)
        .where(
            or_(
                User.is_admin.is_(True),
                User.can_edit_integration_settings.is_(True),
            )
        )
        .order_by(User.email)
    ).all()
    return [
        IntegrationEditorOut(
            id=u.id,
            email=u.email,
            is_admin=u.is_admin,
            can_edit_integration_settings=u.can_edit_integration_settings,
        )
        for u in rows
    ]


@router.post(
    "/integration-settings-editors",
    response_model=IntegrationEditorOut,
    status_code=status.HTTP_201_CREATED,
)
def add_integration_settings_editor(
    body: AddIntegrationEditorIn,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_integration_editors_manager),
) -> IntegrationEditorOut:
    email_norm = body.email.strip().lower()
    user = db.scalars(select(User).where(User.email == email_norm)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь с такой электронной почтой не найден",
        )
    user.can_edit_integration_settings = True
    db.add(user)
    db.commit()
    db.refresh(user)
    return IntegrationEditorOut(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        can_edit_integration_settings=user.can_edit_integration_settings,
    )


@router.delete("/integration-settings-editors/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_integration_settings_editor_flag(
    user_id: UUID,
    db: Session = Depends(get_db),
    actor: User = Depends(get_super_settings_admin),
) -> None:
    if user_id == actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нельзя отозвать права у своей учётной записи",
        )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )
    user.can_edit_integration_settings = False
    user.is_admin = False
    db.add(user)
    db.commit()
