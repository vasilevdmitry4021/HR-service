"""Один цикл синхронизации: чтение каналов, вложения, профили, дедупликация."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import cast as sa_cast, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from app.models.candidate_profile import (
    CandidateContact,
    CandidateProfile,
    CandidateSourceLink,
)
from app.models.telegram_models import (
    TelegramAccount,
    TelegramMessage,
    TelegramMessageAttachment,
    TelegramSource,
    TelegramSyncRun,
)
from app.services import encryption
from telegram_ingestion.config import (
    TELEGRAM_ALLOWED_ATTACHMENT_EXTS,
    TELEGRAM_ATTACHMENTS_DIR,
    TELEGRAM_MAX_ATTACHMENT_BYTES,
    TELEGRAM_RESUME_CLASSIFIER_ENABLED,
    TELEGRAM_SYNC_BATCH_SIZE,
)
from telegram_ingestion.services.attachment_text import extract_text_from_bytes
from telegram_ingestion.services.candidate_extractor import (
    extract_candidate_fields,
    telegram_source_entry,
)
from telegram_ingestion.services.resume_classifier import classify_resume_text
from telegram_ingestion.services.telegram_client import (
    TelegramIngestionError,
    fetch_messages_for_source,
    map_telegram_access_error,
)


def _resolved_about_from_extract(ext: dict[str, Any], combined: str) -> str | None:
    """Текст «О себе» для профиля: краткий из extract, иначе из norm или весь combined."""
    a = ext.get("about")
    if isinstance(a, str) and a.strip():
        return a.strip()[:8000]
    np = ext.get("normalized_payload")
    if isinstance(np, dict):
        na = np.get("about")
        if isinstance(na, str) and na.strip():
            return na.strip()[:8000]
    c = (combined or "").strip()
    return c[:8000] if c else None

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _norm_email(value: str) -> str:
    return (value or "").strip().lower()


def _norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _norm_telegram(value: str) -> str:
    return (value or "").strip().lstrip("@").lower()


def _safe_filename(name: str, max_len: int = 120) -> str:
    base = os.path.basename(name or "file")
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in base)[:max_len]


def _profile_for_telegram_message(
    db: Session, message_id: uuid.UUID
) -> CandidateProfile | None:
    sid = str(message_id)
    prof = db.scalars(
        select(CandidateProfile).where(
            CandidateProfile.source_type == "telegram",
            CandidateProfile.source_resume_id == sid,
        )
    ).first()
    if prof:
        return prof
    link = db.scalars(
        select(CandidateSourceLink).where(
            CandidateSourceLink.source_type == "telegram",
            CandidateSourceLink.source_id == sid,
        )
    ).first()
    if link:
        return db.get(CandidateProfile, link.candidate_id)
    return None


def _profile_from_content_hash(
    db: Session, owner_id: uuid.UUID, content_hash: str
) -> CandidateProfile | None:
    if not content_hash:
        return None
    dup_msg = db.scalars(
        select(TelegramMessage)
        .join(TelegramSource, TelegramSource.id == TelegramMessage.source_id)
        .join(TelegramAccount, TelegramAccount.id == TelegramSource.account_id)
        .where(TelegramAccount.owner_id == owner_id)
        .where(TelegramMessage.content_hash == content_hash)
        .limit(1)
    ).first()
    if not dup_msg:
        return None
    return _profile_for_telegram_message(db, dup_msg.id)


def _profile_from_file_hash(
    db: Session, owner_id: uuid.UUID, file_hash: str
) -> CandidateProfile | None:
    if not file_hash:
        return None
    att = db.scalars(
        select(TelegramMessageAttachment)
        .join(TelegramMessage, TelegramMessage.id == TelegramMessageAttachment.message_id)
        .join(TelegramSource, TelegramSource.id == TelegramMessage.source_id)
        .join(TelegramAccount, TelegramAccount.id == TelegramSource.account_id)
        .where(TelegramAccount.owner_id == owner_id)
        .where(TelegramMessageAttachment.file_hash == file_hash)
        .limit(1)
    ).first()
    if not att:
        return None
    return _profile_for_telegram_message(db, att.message_id)


def _profile_from_contact(
    db: Session,
    owner_id: uuid.UUID,
    contact_type: str,
    contact_value: str,
) -> CandidateProfile | None:
    if not contact_value:
        return None
    return db.scalars(
        select(CandidateProfile)
        .join(
            CandidateContact,
            CandidateContact.candidate_id == CandidateProfile.id,
        )
        .join(
            TelegramMessage,
            TelegramMessage.id
            == sa_cast(CandidateProfile.source_resume_id, PGUUID(as_uuid=True)),
        )
        .join(TelegramSource, TelegramSource.id == TelegramMessage.source_id)
        .join(TelegramAccount, TelegramAccount.id == TelegramSource.account_id)
        .where(TelegramAccount.owner_id == owner_id)
        .where(CandidateProfile.source_type == "telegram")
        .where(CandidateContact.contact_type == contact_type)
        .where(CandidateContact.contact_value == contact_value)
        .limit(1)
    ).first()


def _find_duplicate_profile(
    db: Session,
    owner_id: uuid.UUID,
    content_hash: str,
    attachment_hashes: list[str],
    ext: dict[str, Any],
) -> CandidateProfile | None:
    hit = _profile_from_content_hash(db, owner_id, content_hash)
    if hit:
        return hit
    for fh in attachment_hashes:
        hit = _profile_from_file_hash(db, owner_id, fh)
        if hit:
            return hit
    contacts = ext.get("contacts") or {}
    for e in contacts.get("emails") or []:
        ne = _norm_email(str(e))
        if len(ne) >= 5:
            hit = _profile_from_contact(db, owner_id, "email", ne)
            if hit:
                return hit
    if contacts.get("email"):
        ne = _norm_email(str(contacts["email"]))
        if len(ne) >= 5:
            hit = _profile_from_contact(db, owner_id, "email", ne)
            if hit:
                return hit
    for p in contacts.get("phones") or []:
        np = _norm_phone(str(p))
        if len(np) >= 10:
            hit = _profile_from_contact(db, owner_id, "phone", np)
            if hit:
                return hit
    if contacts.get("phone"):
        np = _norm_phone(str(contacts["phone"]))
        if len(np) >= 10:
            hit = _profile_from_contact(db, owner_id, "phone", np)
            if hit:
                return hit
    for h in contacts.get("telegram_handles") or []:
        nt = _norm_telegram(str(h))
        if len(nt) >= 3:
            hit = _profile_from_contact(db, owner_id, "telegram", nt)
            if hit:
                return hit
    if contacts.get("telegram"):
        nt = _norm_telegram(str(contacts["telegram"]))
        if len(nt) >= 3:
            hit = _profile_from_contact(db, owner_id, "telegram", nt)
            if hit:
                return hit
    return None


def _contact_row_exists(
    db: Session, candidate_id: uuid.UUID, ctype: str, value: str
) -> bool:
    return bool(
        db.scalar(
            select(CandidateContact.id).where(
                CandidateContact.candidate_id == candidate_id,
                CandidateContact.contact_type == ctype,
                CandidateContact.contact_value == value,
            )
        )
    )


def _add_contact_rows(db: Session, candidate_id: uuid.UUID, ext: dict[str, Any]) -> None:
    contacts = ext.get("contacts") or {}
    seen: set[tuple[str, str]] = set()
    for e in contacts.get("emails") or []:
        ne = _norm_email(str(e))
        if len(ne) < 5:
            continue
        key = ("email", ne)
        if key in seen:
            continue
        seen.add(key)
        if not _contact_row_exists(db, candidate_id, "email", ne):
            db.add(
                CandidateContact(
                    candidate_id=candidate_id,
                    contact_type="email",
                    contact_value=ne,
                    is_verified=False,
                )
            )
    for p in contacts.get("phones") or []:
        np = _norm_phone(str(p))
        if len(np) < 10:
            continue
        key = ("phone", np)
        if key in seen:
            continue
        seen.add(key)
        if not _contact_row_exists(db, candidate_id, "phone", np):
            db.add(
                CandidateContact(
                    candidate_id=candidate_id,
                    contact_type="phone",
                    contact_value=np,
                    is_verified=False,
                )
            )
    for h in contacts.get("telegram_handles") or []:
        nt = _norm_telegram(str(h))
        if len(nt) < 3:
            continue
        key = ("telegram", nt)
        if key in seen:
            continue
        seen.add(key)
        if not _contact_row_exists(db, candidate_id, "telegram", nt):
            db.add(
                CandidateContact(
                    candidate_id=candidate_id,
                    contact_type="telegram",
                    contact_value=nt,
                    is_verified=False,
                )
            )


def _source_link_exists(db: Session, candidate_id: uuid.UUID, msg_id: str) -> bool:
    return bool(
        db.scalar(
            select(CandidateSourceLink.id).where(
                CandidateSourceLink.candidate_id == candidate_id,
                CandidateSourceLink.source_type == "telegram",
                CandidateSourceLink.source_id == msg_id,
            )
        )
    )


def _ensure_source_link(
    db: Session,
    candidate_id: uuid.UUID,
    msg_id: str,
    source_url: str | None,
) -> None:
    if _source_link_exists(db, candidate_id, msg_id):
        return
    db.add(
        CandidateSourceLink(
            candidate_id=candidate_id,
            source_type="telegram",
            source_id=msg_id,
            source_url=source_url,
        )
    )


def _merge_telegram_meta(
    existing_norm: dict[str, Any],
    new_entry: dict[str, Any],
    new_attachments_meta: list[dict[str, Any]],
) -> dict[str, Any]:
    out = dict(existing_norm) if isinstance(existing_norm, dict) else {}
    tg = out.get("telegram")
    if not isinstance(tg, dict):
        tg = {}
    sources = tg.get("sources")
    if not isinstance(sources, list):
        sources = []
    sources = list(sources)
    sources.append(new_entry)
    tg["sources"] = sources
    prev_att = tg.get("attachments")
    if not isinstance(prev_att, list):
        prev_att = []
    tg["attachments"] = list(prev_att) + list(new_attachments_meta)
    out["telegram"] = tg
    return out


def _merge_profile_fields(
    prof: CandidateProfile,
    ext: dict[str, Any],
    combined_text: str,
    conf: float,
) -> None:
    if not prof.full_name and ext.get("full_name"):
        prof.full_name = ext.get("full_name")
    if not prof.title and ext.get("title"):
        prof.title = ext.get("title")
    if ext.get("education") is not None and prof.education is None:
        prof.education = ext.get("education")
    if ext.get("work_experience") is not None and prof.work_experience is None:
        prof.work_experience = ext.get("work_experience")
    if ext.get("area") and not prof.area:
        prof.area = ext.get("area")
    if ext.get("experience_years") is not None:
        if prof.experience_years is None:
            prof.experience_years = ext.get("experience_years")
    if ext.get("salary_amount") is not None:
        if prof.salary_amount is None:
            prof.salary_amount = ext.get("salary_amount")
            prof.salary_currency = ext.get("salary_currency") or "RUR"
    new_skills = ext.get("skills") or []
    if new_skills:
        old = prof.skills
        merged: list[str] = []
        if isinstance(old, list):
            merged = [str(s) for s in old if s]
        for s in new_skills:
            if s and str(s) not in merged:
                merged.append(str(s))
        prof.skills = merged[:40]
    prev = (prof.raw_text or "").strip()
    chunk = combined_text.strip()
    if chunk:
        if prev and chunk not in prev:
            prof.raw_text = (prev + "\n\n---\n\n" + chunk)[:50000]
        elif not prev:
            prof.raw_text = chunk[:50000]
    resolved_about = _resolved_about_from_extract(ext, chunk)
    if resolved_about:
        prof.about = resolved_about
    if prof.parse_confidence is None or (conf and conf > (prof.parse_confidence or 0)):
        prof.parse_confidence = conf
    prof.contacts = ext.get("contacts")


async def _sync_one_source(db: Session, source: TelegramSource) -> tuple[int, int, str | None]:
    account = db.get(TelegramAccount, source.account_id)
    if not account or account.auth_status != "authorized":
        return 0, 0, "Аккаунт Telegram не подключён или не авторизован"
    if source.telegram_id == 0:
        logger.info("skip source %s: telegram_id not set", source.id)
        return 0, 0, "Источник не разрешён: нет идентификатора чата или канала"
    owner_id = account.owner_id
    try:
        api_id = int(str(account.api_id).strip())
        api_hash = encryption.decrypt_secret(account.encrypted_api_hash)
        if not account.encrypted_session:
            return 0, 0, "нет сохранённой сессии"
        session_str = encryption.decrypt_secret(account.encrypted_session)
    except Exception as exc:
        logger.warning("decrypt credentials failed: %s", exc)
        return 0, 0, str(exc)

    min_id = int(source.last_message_id) if source.last_message_id else None
    try:
        rows = await fetch_messages_for_source(
            api_id,
            api_hash,
            session_str,
            int(source.telegram_id),
            limit=TELEGRAM_SYNC_BATCH_SIZE,
            min_id=min_id,
            allowed_extensions=TELEGRAM_ALLOWED_ATTACHMENT_EXTS,
            max_attachment_bytes=TELEGRAM_MAX_ATTACHMENT_BYTES,
        )
    except TelegramIngestionError as exc:
        logger.warning("telegram fetch policy for source %s: %s", source.id, exc)
        source.access_status = exc.access_status
        source.error_message = str(exc)[:500]
        source.updated_at = datetime.now(timezone.utc)
        return 0, 0, str(exc)
    except Exception as exc:
        logger.exception("telethon fetch failed for source %s: %s", source.id, exc)
        st, em = map_telegram_access_error(exc)
        source.access_status = st
        source.error_message = em
        source.updated_at = datetime.now(timezone.utc)
        return 0, 0, em

    storage_root = Path(TELEGRAM_ATTACHMENTS_DIR)
    storage_root.mkdir(parents=True, exist_ok=True)

    processed = 0
    candidates = 0
    max_mid = min_id or 0
    for row in rows:
        tid = int(row["telegram_message_id"])
        max_mid = max(max_mid, tid)
        text = row.get("text") or ""
        att_parts: list[str] = []
        attachment_hashes: list[str] = []
        attachment_meta_for_norm: list[dict[str, Any]] = []
        attachment_db_rows: list[tuple[str, str, str, str]] = []
        raw_atts = row.get("attachments") or []

        for spec in raw_atts:
            data = spec.get("bytes")
            if not isinstance(data, bytes):
                continue
            fh = _file_hash(data)
            attachment_hashes.append(fh)
            ftype = str(spec.get("file_type") or "").lower()
            extracted = extract_text_from_bytes(ftype, data)
            if extracted.strip():
                att_parts.append(f"[Вложение: {spec.get('filename')}]\n{extracted}")
            rel_dir = f"{source.id}/{tid}"
            safe = _safe_filename(str(spec.get("filename") or f"file.{ftype}"))
            rel_path = f"{rel_dir}/{uuid.uuid4().hex[:10]}_{safe}"
            full_path = storage_root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_bytes(data)
            attachment_meta_for_norm.append(
                {
                    "file_type": ftype,
                    "file_path": rel_path,
                    "file_hash": fh,
                    "filename": spec.get("filename"),
                    "extracted_preview": (extracted[:500] + "…")
                    if len(extracted) > 500
                    else extracted,
                }
            )
            attachment_db_rows.append(
                (ftype, rel_path, fh, extracted[:65000] if extracted else "")
            )

        parts: list[str] = []
        if text.strip():
            parts.append(text.strip())
        if att_parts:
            parts.extend(att_parts)
        combined = "\n\n".join(parts)
        if not combined.strip():
            continue

        h = _content_hash(combined)
        exists = db.scalar(
            select(TelegramMessage.id).where(
                TelegramMessage.source_id == source.id,
                TelegramMessage.telegram_message_id == tid,
            )
        )
        if exists:
            continue

        att_text_len = sum(len(p) for p in att_parts)
        if TELEGRAM_RESUME_CLASSIFIER_ENABLED:
            is_cv, conf = classify_resume_text(combined)
            if not is_cv and att_text_len > 400:
                is_cv = True
                conf = max(conf, 0.55)
        else:
            is_cv, conf = True, 1.0

        ext: dict[str, Any] = {}
        norm: dict[str, Any] = {}
        dup: CandidateProfile | None = None
        if is_cv:
            src_entry = telegram_source_entry(
                source_id=str(source.id),
                source_display_name=source.display_name,
                source_link=source.link,
                telegram_message_id=tid,
                message_link=row.get("message_link"),
                published_at=row.get("published_at"),
            )
            has_attachment_text = bool(att_parts)
            if has_attachment_text:
                attachment_text = "\n\n".join(att_parts)
                ext = extract_candidate_fields(
                    attachment_text,
                    telegram_meta={
                        "sources": [src_entry],
                        "attachments": attachment_meta_for_norm,
                    },
                    message_caption=text or "",
                    is_attachment_text=True,
                )
                ext["raw_text"] = combined
            else:
                ext = extract_candidate_fields(
                    text,
                    telegram_meta={
                        "sources": [src_entry],
                        "attachments": attachment_meta_for_norm,
                    },
                    message_caption=None,
                    is_attachment_text=False,
                )
            norm = ext.get("normalized_payload") or {}
            dup = _find_duplicate_profile(
                db, owner_id, h, attachment_hashes, ext
            )

        msg = TelegramMessage(
            source_id=source.id,
            telegram_message_id=tid,
            published_at=row.get("published_at"),
            author_id=row.get("author_id"),
            author_name=row.get("author_name"),
            text=text or None,
            message_link=row.get("message_link"),
            content_hash=h,
            parse_status="processed" if is_cv else "skipped",
            is_resume_candidate=is_cv,
            confidence_score=conf,
        )
        db.add(msg)
        db.flush()

        for ftype, rel_path, fh, extracted in attachment_db_rows:
            db.add(
                TelegramMessageAttachment(
                    message_id=msg.id,
                    file_type=ftype,
                    file_path=rel_path,
                    file_hash=fh,
                    extracted_text=extracted or None,
                )
            )

        processed += 1

        if not is_cv:
            continue

        if dup:
            merged_norm = _merge_telegram_meta(
                dup.normalized_payload
                if isinstance(dup.normalized_payload, dict)
                else {},
                src_entry,
                attachment_meta_for_norm,
            )
            _merge_profile_fields(dup, ext, combined, conf)
            merged_norm.update(
                {
                    "source_type": "telegram",
                    "full_name": dup.full_name,
                    "title": dup.title,
                    "skills": dup.skills,
                    "contacts": dup.contacts
                    if isinstance(dup.contacts, dict)
                    else ext.get("contacts"),
                    "about": (dup.about or "")[:8000] if dup.about else None,
                    "experience_years": dup.experience_years,
                    "salary_amount": dup.salary_amount,
                    "salary_currency": dup.salary_currency,
                    "area": dup.area,
                    "education": dup.education,
                    "work_experience": dup.work_experience,
                }
            )
            dup.normalized_payload = merged_norm
            _add_contact_rows(db, dup.id, ext)
            _ensure_source_link(db, dup.id, str(msg.id), row.get("message_link"))
            continue

        prof = CandidateProfile(
            source_type="telegram",
            source_resume_id=str(msg.id),
            source_url=row.get("message_link"),
            full_name=ext.get("full_name"),
            title=ext.get("title"),
            area=ext.get("area"),
            experience_years=ext.get("experience_years"),
            skills=ext.get("skills"),
            salary_amount=ext.get("salary_amount"),
            salary_currency=ext.get("salary_currency"),
            contacts=ext.get("contacts"),
            about=_resolved_about_from_extract(ext, combined),
            education=ext.get("education"),
            work_experience=ext.get("work_experience"),
            raw_text=combined[:50000],
            normalized_payload=norm,
            parse_confidence=conf,
        )
        db.add(prof)
        db.flush()
        _add_contact_rows(db, prof.id, ext)
        _ensure_source_link(db, prof.id, str(msg.id), row.get("message_link"))
        candidates += 1

    source.last_message_id = max_mid if max_mid else source.last_message_id
    source.last_sync_at = datetime.now(timezone.utc)
    source.access_status = "active"
    source.error_message = None
    account.last_sync_at = datetime.now(timezone.utc)
    return processed, candidates, None


def _run_sync_coro(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _finalize_sync_run(
    db: Session,
    run: TelegramSyncRun,
    proc: int,
    cands: int,
    err: str | None,
) -> None:
    run.messages_processed = proc
    run.candidates_created = cands
    run.finished_at = datetime.now(timezone.utc)
    if err:
        run.status = "failed"
        run.error_log = {"error": err[:800]}
    else:
        run.status = "completed"
        run.error_log = None


def process_queued_sync_runs(db: Session) -> None:
    """Обработать запуски со статусом queued (ручной sync из API)."""
    queued = list(
        db.scalars(
            select(TelegramSyncRun)
            .where(TelegramSyncRun.status == "queued")
            .order_by(TelegramSyncRun.started_at.asc())
            .limit(50)
        ).all()
    )
    if not queued:
        return
    logger.info("telegram sync: %s queued runs", len(queued))
    for run in queued:
        src = db.get(TelegramSource, run.source_id)
        if not src:
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error_log = {"error": "Источник удалён"}
            try:
                db.commit()
            except Exception:
                logger.exception("commit failed (queued run orphan)")
                db.rollback()
            continue
        run.status = "running"
        db.flush()
        err: str | None = None
        proc, cands = 0, 0
        try:
            proc, cands, err = _run_sync_coro(_sync_one_source(db, src))
        except Exception as exc:
            logger.exception("queued sync run %s", run.id)
            err = str(exc)
        _finalize_sync_run(db, run, proc, cands, err)
        try:
            db.commit()
        except Exception:
            logger.exception("commit failed")
            db.rollback()


def run_once(db: Session) -> None:
    process_queued_sync_runs(db)
    stmt = (
        select(TelegramSource)
        .join(TelegramAccount, TelegramAccount.id == TelegramSource.account_id)
        .where(
            TelegramSource.is_enabled.is_(True),
            TelegramAccount.auth_status == "authorized",
        )
    )
    sources = list(db.scalars(stmt).all())
    logger.info("telegram sync: %s enabled sources", len(sources))
    for src in sources:
        run = TelegramSyncRun(
            source_id=src.id,
            status="running",
            messages_processed=0,
            candidates_created=0,
        )
        db.add(run)
        db.flush()
        err: str | None = None
        proc, cands = 0, 0
        try:
            proc, cands, err = _run_sync_coro(_sync_one_source(db, src))
        except Exception as exc:
            logger.exception("sync source %s", src.id)
            err = str(exc)
        _finalize_sync_run(db, run, proc, cands, err)
        try:
            db.commit()
        except Exception:
            logger.exception("commit failed")
            db.rollback()
