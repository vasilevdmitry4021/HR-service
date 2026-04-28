"""Сервис записи журнала запросов в PostgreSQL и JSON-файл."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any

from app.config import settings
from app.db.session import SessionLocal
from app.models.request_log import RequestLog

logger = logging.getLogger(__name__)

_SENSITIVE_FIELDS = frozenset(
    {"password", "api_key", "client_secret", "access_token", "refresh_token"}
)
_TOKEN_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*")


def _mask_sensitive(data: dict[str, Any]) -> dict[str, Any]:
    return {k: ("***" if k in _SENSITIVE_FIELDS else v) for k, v in data.items()}


def _mask_tokens_in_text(text: str | None) -> str | None:
    if text is None:
        return None
    return _TOKEN_RE.sub(r"\1***", text)


def _build_file_handler() -> RotatingFileHandler | None:
    path = settings.request_log_file_path
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=settings.request_log_file_max_bytes,
            backupCount=settings.request_log_file_backup_count,
            encoding="utf-8",
        )
        handler.setLevel(logging.INFO)
        return handler
    except Exception:
        logger.exception("Не удалось создать файловый обработчик журнала запросов")
        return None


_file_handler: RotatingFileHandler | None = None


def _get_file_handler() -> RotatingFileHandler | None:
    global _file_handler
    if _file_handler is None and settings.request_log_enabled:
        _file_handler = _build_file_handler()
    return _file_handler


def write_request_log(
    *,
    request_id: str,
    query_id: str | None,
    user_id: uuid.UUID | None,
    user_email: str | None,
    method: str,
    route: str,
    route_tag: str,
    status_code: int,
    duration_ms: int,
    request_body_summary: dict[str, Any] | None,
    response_summary: dict[str, Any] | None,
    search_metrics: dict[str, Any] | None,
    integration_calls: list[dict[str, Any]] | None,
    error_type: str | None,
    error_message: str | None,
) -> None:
    """Записывает одну запись журнала в PostgreSQL и JSON-файл.

    Вызывается из фонового потока или BackgroundTask -- не блокирует обработчик запроса.
    """
    if not settings.request_log_enabled:
        return

    if request_body_summary:
        request_body_summary = _mask_sensitive(request_body_summary)
    error_message = _mask_tokens_in_text(error_message)

    # Снимок всех полей в обычный словарь: это позволяет избежать
    # DetachedInstanceError при обращении к атрибутам ORM-объекта после
    # закрытия сессии в _write_to_db.
    snapshot: dict[str, Any] = {
        "request_id": request_id,
        "query_id": query_id,
        "user_id": str(user_id) if user_id else None,
        "user_email": user_email,
        "method": method,
        "route": route,
        "route_tag": route_tag,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "request_body_summary": request_body_summary,
        "response_summary": response_summary,
        "search_metrics": search_metrics,
        "integration_calls": integration_calls,
        "error_type": error_type,
        "error_message": error_message,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    _write_to_db(snapshot)
    _write_to_file(snapshot)


def _write_to_db(snapshot: dict[str, Any]) -> None:
    record = RequestLog(
        request_id=snapshot["request_id"],
        query_id=snapshot["query_id"],
        user_id=snapshot["user_id"],
        user_email=snapshot["user_email"],
        method=snapshot["method"],
        route=snapshot["route"],
        route_tag=snapshot["route_tag"],
        status_code=snapshot["status_code"],
        duration_ms=snapshot["duration_ms"],
        request_body_summary=snapshot["request_body_summary"],
        response_summary=snapshot["response_summary"],
        search_metrics=snapshot["search_metrics"],
        integration_calls=snapshot["integration_calls"],
        error_type=snapshot["error_type"],
        error_message=snapshot["error_message"],
    )
    db = SessionLocal()
    try:
        db.add(record)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Ошибка при записи в request_log (PostgreSQL): request_id=%s",
            snapshot["request_id"],
        )
    finally:
        db.close()


def _write_to_file(snapshot: dict[str, Any]) -> None:
    handler = _get_file_handler()
    if handler is None:
        return
    try:
        line = json.dumps(snapshot, ensure_ascii=False, default=str)
        log_record = logging.LogRecord(
            name="request_log",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=line,
            args=(),
            exc_info=None,
        )
        handler.emit(log_record)
    except Exception:
        logger.exception(
            "Ошибка при записи в request_log (файл): request_id=%s",
            snapshot.get("request_id"),
        )


def cleanup_old_request_logs(retention_days: int | None = None) -> int:
    """Удаляет записи старше retention_days дней. Возвращает количество удалённых строк."""
    from datetime import timedelta

    from sqlalchemy import delete

    days = retention_days if retention_days is not None else settings.request_log_retention_days
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

    db = SessionLocal()
    try:
        result = db.execute(
            delete(RequestLog).where(RequestLog.created_at < cutoff)
        )
        db.commit()
        deleted = result.rowcount
        if deleted:
            logger.info("Очистка request_log: удалено %d записей старше %d дней", deleted, days)
        return deleted
    except Exception:
        db.rollback()
        logger.exception("Ошибка при очистке request_log")
        return 0
    finally:
        db.close()
