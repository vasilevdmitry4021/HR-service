from __future__ import annotations

import asyncio
import hashlib
import logging
import time as time_monotonic
import uuid
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_settings_admin
from app.api.hh_access import ensure_hh_access_token
from app.config import get_estaff_credentials_from_db, settings
from app.models.candidate_profile import CandidateProfile
from app.models.estaff_export import EstaffExport, EstaffExportStatus
from app.models.favorite import Favorite
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.estaff import (
    MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS,
    EstaffCredentialsIn,
    EstaffCredentialsPutOut,
    EstaffCredentialsStatusOut,
    EstaffExportBatchOut,
    EstaffExportLatestBatchIn,
    EstaffExportLatestBatchItemOut,
    EstaffExportLatestBatchOut,
    EstaffExportLatestOut,
    EstaffExportRequestIn,
    EstaffExportResultOut,
    EstaffExportRowOut,
    EstaffExportsListOut,
    EstaffUserCheckOut,
    EstaffUserCheckRequestIn,
    EstaffVacanciesListOut,
    EstaffVacancyItemOut,
)
from app.services import encryption, hh_client
from app.services.candidate_unified import candidate_profile_to_export_norm
from app.services.estaff_candidate_prepare import (
    EstaffMandatoryDataError,
    prepare_candidate_payload_for_export,
)
from app.services.estaff_hr_bundle import prepare_hr_llm_bundle_for_export_item
from app.services.telegram_search import telegram_profile_owned_by_user
from app.services.estaff_client import (
    EStaffClientError,
    EstaffVacancyRow,
    create_candidate_in_estaff,
    fetch_user_by_login,
    fetch_get_voc,
    fetch_open_vacancies,
)
from app.services.hh_client import HHClientError
from app.services.hh_resume_contacts import contacts_from_hh_raw

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/estaff", tags=["estaff"])

_vacancies_cache: dict[str, tuple[float, list[EstaffVacancyRow]]] = {}

MAX_EXPORT_ITEMS = MAX_ESTAFF_EXPORT_BATCH_RESUME_IDS
DEFAULT_EXPORTS_PAGE = 1
DEFAULT_EXPORTS_PER_PAGE = 20
MAX_EXPORTS_PER_PAGE = 100

# Сообщения об ошибках в БД не должны раздувать строки и ломать интерфейс.
_MAX_ERROR_MESSAGE_DB_LEN = 500


def _shorten_error_message_for_db(text: str, max_len: int = _MAX_ERROR_MESSAGE_DB_LEN) -> str:
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _looks_like_internal_profile_uuid(candidate_id: str) -> bool:
    """UUID профиля Telegram; id резюме HeadHunter обычно не в формате UUID."""
    try:
        uuid.UUID((candidate_id or "").strip())
    except ValueError:
        return False
    return True


def _legacy_hh_resume_id_field(stored_candidate_key: str) -> str | None:
    """Устаревшее поле ответа: только для кандидатов HeadHunter (не UUID-профиль)."""
    if _looks_like_internal_profile_uuid(stored_candidate_key):
        return None
    return stored_candidate_key


def _merge_favorite_contacts_into_hh_norm(
    db: Session,
    user_id: uuid.UUID,
    resume_key: str,
    norm: dict[str, Any],
) -> None:
    """
    Если в избранном у пользователя для этого hh_resume_id заданы contact_email / contact_phone,
    подмешивает их в _raw.contact для подготовки выгрузки (когда в ответе HH контактов нет).
    """
    key = (resume_key or "").strip()
    if not key:
        return
    fav = db.scalar(
        select(Favorite).where(
            Favorite.user_id == user_id,
            Favorite.hh_resume_id == key,
        )
    )
    if fav is None:
        return
    email = (fav.contact_email or "").strip() or None
    phone = (fav.contact_phone or "").strip() or None
    if not email and not phone:
        return

    raw_any = norm.get("_raw")
    if not isinstance(raw_any, dict):
        raw_any = {}
        norm["_raw"] = raw_any

    existing_email, existing_phone = contacts_from_hh_raw(raw_any)

    contact_list = raw_any.get("contact")
    if not isinstance(contact_list, list):
        contact_list = []
        raw_any["contact"] = contact_list

    if email and not existing_email:
        contact_list.append({"type": {"id": "email"}, "value": email})
    if phone and not existing_phone:
        contact_list.append({"type": {"id": "cell"}, "value": phone})


def _telegram_profile_by_candidate_id(
    db: Session, candidate_id: str
) -> CandidateProfile | None:
    try:
        uid = uuid.UUID((candidate_id or "").strip())
    except ValueError:
        return None
    p = db.get(CandidateProfile, uid)
    if p and p.source_type == "telegram":
        return p
    return None


def _detail_dict(row: EstaffExport) -> dict[str, Any]:
    d = row.export_detail
    return d if isinstance(d, dict) else {}


def _warnings_from_detail(d: dict[str, Any]) -> list[str] | None:
    raw = d.get("preparation_warnings")
    if not isinstance(raw, list):
        return None
    out = [str(x).strip() for x in raw if str(x).strip()]
    return out or None


def _error_stage_for_response(row: EstaffExport) -> str | None:
    if row.status == EstaffExportStatus.success.value:
        return None
    st = _detail_dict(row).get("error_stage")
    if st is None or not str(st).strip():
        return None
    return str(st).strip()


def _latest_batch_item_from_row(row: EstaffExport) -> EstaffExportLatestBatchItemOut:
    d = _detail_dict(row)
    key = row.hh_resume_id
    return EstaffExportLatestBatchItemOut(
        candidate_id=key,
        hh_resume_id=_legacy_hh_resume_id_field(key),
        found=True,
        export_id=str(row.id),
        status=row.status,
        estaff_candidate_id=row.estaff_candidate_id,
        error_message=row.error_message,
        error_stage=_error_stage_for_response(row),
        preparation_warnings=_warnings_from_detail(d),
        exported_at=row.exported_at,
        created_at=row.created_at,
    )


def _result_from_row(row: EstaffExport, *, api_error_message: str | None = None) -> EstaffExportResultOut:
    err_out = api_error_message
    if row.status == EstaffExportStatus.success.value:
        err_out = None
    detail = _detail_dict(row)
    key = row.hh_resume_id
    return EstaffExportResultOut(
        export_id=str(row.id),
        candidate_id=key,
        hh_resume_id=_legacy_hh_resume_id_field(key),
        status=row.status,
        estaff_candidate_id=row.estaff_candidate_id,
        estaff_vacancy_id=row.estaff_vacancy_id,
        error_message=err_out,
        error_stage=_error_stage_for_response(row),
        preparation_warnings=_warnings_from_detail(detail),
        exported_at=row.exported_at,
        created_at=row.created_at,
    )


@router.get("/credentials", response_model=EstaffCredentialsStatusOut)
def get_estaff_credentials_status(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> EstaffCredentialsStatusOut:
    return EstaffCredentialsStatusOut(
        configured=get_estaff_credentials_from_db(db) is not None,
    )


@router.put("/credentials", response_model=EstaffCredentialsPutOut)
def put_estaff_credentials(
    body: EstaffCredentialsIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_settings_admin),
) -> EstaffCredentialsPutOut:
    payload = {
        "server_name": body.server_name.strip(),
        "api_token": body.api_token.strip(),
    }
    blob = encryption.encrypt_json(payload)
    row = db.scalars(
        select(SystemSettings).where(SystemSettings.key == "estaff_credentials")
    ).first()
    if row:
        row.encrypted_value = blob
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(SystemSettings(key="estaff_credentials", encrypted_value=blob))
    db.commit()
    logger.info(
        "estaff_credentials_updated",
        extra={"user_id": str(user.id)},
    )
    return EstaffCredentialsPutOut()


def _vacancies_cache_key(
    server_name: str,
    api_token: str,
    vacancies_path: str,
    date_min_iso: str,
    date_max_iso: str,
) -> str:
    return hashlib.sha256(
        f"{server_name}\0{api_token}\0{vacancies_path}\0{date_min_iso}\0{date_max_iso}".encode()
    ).hexdigest()


def _vacancy_find_iso_bounds(
    min_start_date: date | None,
    max_start_date: date | None,
) -> tuple[str, str]:
    """Пара ISO-строк для filter e-staff: начало/конец календарного дня в Z."""
    if min_start_date is None and max_start_date is None:
        y = datetime.now(timezone.utc).year
        return (
            f"{y:04d}-01-01T00:00:00.000Z",
            f"{y:04d}-12-31T23:59:59.999Z",
        )
    if min_start_date is not None and max_start_date is not None:
        return (
            f"{min_start_date.isoformat()}T00:00:00.000Z",
            f"{max_start_date.isoformat()}T23:59:59.999Z",
        )
    raise ValueError("min_start_date и max_start_date должны быть заданы вместе")


@router.get("/vacancies", response_model=EstaffVacanciesListOut)
async def list_estaff_vacancies(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    min_start_date: date | None = Query(None),
    max_start_date: date | None = Query(None),
) -> EstaffVacanciesListOut:
    if (min_start_date is None) != (max_start_date is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Укажите оба параметра min_start_date и max_start_date или ни одного",
        )
    if min_start_date is not None and max_start_date is not None:
        if min_start_date > max_start_date:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="min_start_date не может быть позже max_start_date",
            )
    creds = get_estaff_credentials_from_db(db)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Подключение к e-staff не настроено",
        )
    server_name, api_token = creds
    ttl = max(0, settings.estaff_vacancies_cache_ttl_seconds)
    vp = (settings.estaff_vacancies_path or "").strip()
    d_min, d_max = _vacancy_find_iso_bounds(min_start_date, max_start_date)
    key = _vacancies_cache_key(server_name, api_token, vp, d_min, d_max)
    now = time_monotonic.monotonic()
    if ttl > 0 and key in _vacancies_cache:
        expires_at, cached_rows = _vacancies_cache[key]
        if now < expires_at:
            return EstaffVacanciesListOut(
                items=[EstaffVacancyItemOut(**r) for r in cached_rows],
            )
    try:
        rows, elapsed = await fetch_open_vacancies(
            server_name,
            api_token,
            min_start_date_iso=d_min,
            max_start_date_iso=d_max,
        )
    except EStaffClientError as exc:
        logger.error(
            "estaff_vacancies_error code=%s detail=%s",
            exc.status_code,
            exc.detail_for_db[:2000],
        )
        msg = exc.user_message
        if settings.estaff_expose_error_detail and exc.detail_for_db.strip():
            short = exc.detail_for_db.strip()[:400]
            if short not in msg:
                msg = f"{msg} [{short}]"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=msg,
        ) from exc
    if ttl > 0:
        _vacancies_cache[key] = (now + float(ttl), list(rows))
    logger.info(
        "estaff_vacancies_ok",
        extra={"user_id": str(user.id), "count": len(rows), "elapsed_s": round(elapsed, 3)},
    )
    return EstaffVacanciesListOut(items=[EstaffVacancyItemOut(**r) for r in rows])


@router.post("/export", response_model=EstaffExportBatchOut)
async def post_estaff_export(
    body: EstaffExportRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EstaffExportBatchOut:
    creds = get_estaff_credentials_from_db(db)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Подключение к e-staff не настроено",
        )
    server_name, api_token = creds
    user_login = body.user_login.strip()
    if not user_login:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Укажите логин пользователя e-staff",
        )

    if len(body.items) > MAX_EXPORT_ITEMS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Не более {MAX_EXPORT_ITEMS} резюме за один запрос",
        )

    needs_hh = any(
        it.candidate is None
        and _telegram_profile_by_candidate_id(db, it.effective_candidate_id()) is None
        for it in body.items
    )

    access: str | None = None
    if needs_hh and not settings.feature_use_mock_hh:
        access = await ensure_hh_access_token(db, user.id)
        if not access:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Подключите HeadHunter для выгрузки резюме",
            )

    logger.info(
        "estaff_export_start",
        extra={"user_id": str(user.id), "count": len(body.items)},
    )

    results: list[EstaffExportResultOut] = []

    for idx, item in enumerate(body.items):
        if idx > 0:
            await asyncio.sleep(0.1)

        cand_key = item.effective_candidate_id()
        vac = str(item.vacancy_id).strip()

        row = EstaffExport(
            user_id=user.id,
            hh_resume_id=cand_key,
            status=EstaffExportStatus.pending.value,
            estaff_vacancy_id=vac,
        )
        db.add(row)
        db.flush()

        prep_warnings: list[str] = []
        payload: dict[str, Any] | None = None

        async def _fetch_voc_items(voc_id: str) -> list[dict[str, Any]]:
            return await fetch_get_voc(server_name, api_token, voc_id)

        try:
            if item.candidate is not None:
                payload = dict(item.candidate)
                prep_warnings.append(
                    "Данные candidate переданы с клиента; разрешение справочников на сервере не выполнялось.",
                )
            else:
                tg_prof = _telegram_profile_by_candidate_id(db, cand_key)
                if tg_prof is not None:
                    if not telegram_profile_owned_by_user(db, tg_prof, user.id):
                        raise PermissionError("Нет доступа к этому кандидату из Telegram")
                    norm = candidate_profile_to_export_norm(tg_prof)
                    payload, w = await prepare_candidate_payload_for_export(
                        norm,
                        server_name=server_name,
                        api_token=api_token,
                        fetch_voc_items=_fetch_voc_items,
                        candidate_export_key=str(tg_prof.id),
                    )
                    prep_warnings.extend(w)
                else:
                    norm = await hh_client.fetch_resume(
                        access,
                        cand_key,
                        keep_raw=True,
                        db=db,
                        hh_token_user_id=user.id,
                    )
                    _merge_favorite_contacts_into_hh_norm(db, user.id, cand_key, norm)
                    payload, w = await prepare_candidate_payload_for_export(
                        norm,
                        server_name=server_name,
                        api_token=api_token,
                        fetch_voc_items=_fetch_voc_items,
                        candidate_export_key=cand_key,
                    )
                    prep_warnings.extend(w)
        except PermissionError as exc:
            row.status = EstaffExportStatus.error.value
            row.error_message = str(exc)
            row.export_detail = {
                "error_stage": "fetch_resume",
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            logger.error(
                "estaff_export_error",
                extra={"candidate_id": cand_key, "kind": "hh_permission"},
            )
            results.append(_result_from_row(row, api_error_message=str(exc)))
            continue
        except HHClientError as exc:
            row.status = EstaffExportStatus.error.value
            row.error_message = _shorten_error_message_for_db(exc.detail)
            row.export_detail = {
                "error_stage": "fetch_resume",
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            logger.error(
                "estaff_export_error",
                extra={"candidate_id": cand_key, "kind": "hh_client", "code": exc.status_code},
            )
            results.append(
                _result_from_row(
                    row,
                    api_error_message=_shorten_error_message_for_db(exc.detail),
                )
            )
            continue
        except EstaffMandatoryDataError as exc:
            row.status = EstaffExportStatus.error.value
            joined = "; ".join(exc.messages)
            row.error_message = _shorten_error_message_for_db(joined)
            row.export_detail = {
                "error_stage": "preparation",
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            logger.error(
                "estaff_export_error",
                extra={"candidate_id": cand_key, "kind": "mandatory_minimum"},
            )
            results.append(
                _result_from_row(
                    row,
                    api_error_message=_shorten_error_message_for_db(joined),
                )
            )
            continue
        except Exception:
            logger.exception("estaff_export_prepare_unexpected")
            row.status = EstaffExportStatus.error.value
            row.error_message = "Внутренняя ошибка при подготовке данных"
            row.export_detail = {
                "error_stage": "preparation",
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            results.append(
                _result_from_row(
                    row,
                    api_error_message="Не удалось подготовить данные для e-staff",
                )
            )
            continue

        if item.include_hr_llm_bundle:
            att, hw = prepare_hr_llm_bundle_for_export_item(
                db,
                user.id,
                cand_key,
                include_bundle=True,
                client_analysis=item.hr_llm_analysis,
                client_summary=item.hr_llm_summary,
                client_score=item.hr_llm_score,
                search_query=item.hr_search_query,
                settings=settings,
            )
            prep_warnings.extend(hw)
            if att is not None:
                payload.setdefault("attachments", []).append(att)

        try:
            estaff_cand_id, elapsed = await create_candidate_in_estaff(
                server_name,
                api_token,
                payload,
                user_login=user_login,
                vacancy_id=item.vacancy_id,
            )
            now = datetime.now(timezone.utc)
            row.status = EstaffExportStatus.success.value
            row.estaff_candidate_id = estaff_cand_id
            row.exported_at = now
            row.error_message = None
            row.export_detail = {
                "error_stage": None,
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            logger.info(
                "estaff_export_ok",
                extra={
                    "candidate_id": cand_key,
                    "estaff_candidate_id": estaff_cand_id,
                    "elapsed_s": round(elapsed, 3),
                },
            )
            results.append(_result_from_row(row))
        except EStaffClientError as exc:
            row.status = EstaffExportStatus.error.value
            row.error_message = _shorten_error_message_for_db(exc.user_message)
            row.export_detail = {
                "error_stage": "estaff_api",
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            logger.error(
                "estaff_export_error candidate_id=%s code=%s detail=%s",
                cand_key,
                exc.status_code,
                exc.detail_for_db[:2000],
            )
            results.append(
                _result_from_row(
                    row,
                    api_error_message=_shorten_error_message_for_db(exc.user_message),
                )
            )
        except Exception:
            logger.exception("estaff_export_estaff_unexpected")
            row.status = EstaffExportStatus.error.value
            row.error_message = "Внутренняя ошибка"
            row.export_detail = {
                "error_stage": "estaff_api",
                "preparation_warnings": prep_warnings,
            }
            db.commit()
            db.refresh(row)
            results.append(
                _result_from_row(
                    row,
                    api_error_message="Не удалось выполнить выгрузку",
                )
            )

    return EstaffExportBatchOut(results=results)


@router.post("/user/check", response_model=EstaffUserCheckOut)
async def post_estaff_user_check(
    body: EstaffUserCheckRequestIn,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> EstaffUserCheckOut:
    creds = get_estaff_credentials_from_db(db)
    if not creds:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Подключение к e-staff не настроено",
        )
    server_name, api_token = creds
    login = body.login.strip()
    if not login:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Укажите логин пользователя e-staff",
        )
    try:
        user_data, _elapsed = await fetch_user_by_login(server_name, api_token, login)
    except EStaffClientError as exc:
        msg = exc.user_message
        if settings.estaff_expose_error_detail and exc.detail_for_db.strip():
            short = exc.detail_for_db.strip()[:400]
            if short not in msg:
                msg = f"{msg} [{short}]"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=msg,
        ) from exc
    user_name = None
    if isinstance(user_data, dict):
        for key in ("name", "full_name", "title"):
            value = user_data.get(key)
            if isinstance(value, str) and value.strip():
                user_name = value.strip()
                break
    return EstaffUserCheckOut(valid=user_data is not None, login=login, user_name=user_name)


@router.get("/exports", response_model=EstaffExportsListOut)
def list_estaff_exports(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(default=DEFAULT_EXPORTS_PAGE, ge=1),
    per_page: int = Query(default=DEFAULT_EXPORTS_PER_PAGE, ge=1, le=MAX_EXPORTS_PER_PAGE),
) -> EstaffExportsListOut:
    total = (
        db.scalar(
            select(func.count())
            .select_from(EstaffExport)
            .where(EstaffExport.user_id == user.id)
        )
        or 0
    )
    offset = (page - 1) * per_page
    rows = db.scalars(
        select(EstaffExport)
        .where(EstaffExport.user_id == user.id)
        .order_by(EstaffExport.created_at.desc())
        .offset(offset)
        .limit(per_page)
    ).all()
    items = [
        EstaffExportRowOut(
            id=str(r.id),
            candidate_id=r.hh_resume_id,
            hh_resume_id=_legacy_hh_resume_id_field(r.hh_resume_id),
            estaff_candidate_id=r.estaff_candidate_id,
            estaff_vacancy_id=r.estaff_vacancy_id,
            status=r.status,
            error_message=r.error_message,
            error_stage=_error_stage_for_response(r),
            preparation_warnings=_warnings_from_detail(_detail_dict(r)),
            exported_at=r.exported_at,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return EstaffExportsListOut(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/exports/latest-batch", response_model=EstaffExportLatestBatchOut)
def post_estaff_exports_latest_batch(
    body: EstaffExportLatestBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EstaffExportLatestBatchOut:
    ids = body.candidate_ids
    if not ids:
        return EstaffExportLatestBatchOut(items=[])
    stmt = (
        select(EstaffExport)
        .where(
            EstaffExport.user_id == user.id,
            EstaffExport.hh_resume_id.in_(ids),
        )
        .distinct(EstaffExport.hh_resume_id)
        .order_by(EstaffExport.hh_resume_id, EstaffExport.created_at.desc())
    )
    rows = db.scalars(stmt).all()
    by_key = {r.hh_resume_id: r for r in rows}
    items = [
        _latest_batch_item_from_row(by_key[k])
        if k in by_key
        else EstaffExportLatestBatchItemOut(
            candidate_id=k,
            hh_resume_id=_legacy_hh_resume_id_field(k),
            found=False,
        )
        for k in ids
    ]
    return EstaffExportLatestBatchOut(items=items)


@router.get("/exports/{candidate_id}", response_model=EstaffExportLatestOut)
def get_estaff_export_for_candidate(
    candidate_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> EstaffExportLatestOut:
    row = db.scalars(
        select(EstaffExport)
        .where(
            EstaffExport.user_id == user.id,
            EstaffExport.hh_resume_id == candidate_id,
        )
        .order_by(EstaffExport.created_at.desc())
    ).first()
    if not row:
        return EstaffExportLatestOut(found=False)
    item = _latest_batch_item_from_row(row)
    return EstaffExportLatestOut(
        found=True,
        export_id=item.export_id,
        candidate_id=item.candidate_id,
        hh_resume_id=item.hh_resume_id,
        status=item.status,
        estaff_candidate_id=item.estaff_candidate_id,
        error_message=item.error_message,
        error_stage=item.error_stage,
        preparation_warnings=item.preparation_warnings,
        exported_at=item.exported_at,
        created_at=item.created_at,
    )
