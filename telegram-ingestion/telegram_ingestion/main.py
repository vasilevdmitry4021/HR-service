"""Точка входа: периодический опрос источников Telegram."""

from __future__ import annotations

import logging
import time

from sqlalchemy import func, select

from app.models.telegram_models import TelegramSyncRun
from telegram_ingestion.config import (
    TELEGRAM_QUEUED_POLL_SECONDS,
    TELEGRAM_SYNC_ENABLED,
    TELEGRAM_SYNC_INTERVAL_SECONDS,
)
from telegram_ingestion.db_session import SessionLocal
from telegram_ingestion.services.sync_sources import run_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def _count_queued(db) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(TelegramSyncRun)
            .where(TelegramSyncRun.status == "queued")
        )
        or 0
    )


def main() -> None:
    if not TELEGRAM_SYNC_ENABLED:
        logging.getLogger(__name__).info("TELEGRAM_SYNC_ENABLED=false, выход")
        return
    log = logging.getLogger(__name__)
    poll_interval = max(5, TELEGRAM_QUEUED_POLL_SECONDS)
    max_wait = max(30, TELEGRAM_SYNC_INTERVAL_SECONDS)

    while True:
        db = SessionLocal()
        try:
            run_once(db)
        except Exception:
            log.exception("цикл синхронизации")
        finally:
            db.close()

        waited = 0
        while waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            db = SessionLocal()
            try:
                queued_count = _count_queued(db)
            finally:
                db.close()
            if queued_count > 0:
                log.info("обнаружена задача в очереди, прерываем ожидание")
                break
