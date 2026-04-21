from __future__ import annotations

import time
import uuid
from threading import Lock
from typing import Any

from app.config import settings
from app.services.ttl_cache import TTLCache

_jobs: TTLCache[dict[str, Any]] = TTLCache(
    ttl_seconds=max(60, int(settings.evaluate_progress_ttl_seconds or 1800)),
    max_items=1000,
)
_lock = Lock()


def create_job(*, user_id: str, snapshot_id: str, total_count: int) -> str:
    job_id = str(uuid.uuid4())
    now = time.monotonic()
    payload: dict[str, Any] = {
        "job_id": job_id,
        "user_id": user_id,
        "snapshot_id": snapshot_id,
        "status": "queued",
        "stage": "queued",
        "total_count": max(0, int(total_count)),
        "processed_count": 0,
        "analyzed_count": 0,
        "analyses": {},
        "processing_time_seconds": None,
        "error": None,
        "cancel_requested": False,
        "has_active_task": False,
        "_task": None,
        "created_monotonic": now,
        "updated_monotonic": now,
    }
    with _lock:
        _jobs.set(job_id, payload)
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        state = _jobs.get(job_id)
        return dict(state) if state else None


def _update(job_id: str, **changes: Any) -> None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        state.update(changes)
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)


def mark_running(job_id: str) -> None:
    _update(job_id, status="running", stage="preparing")


def attach_task(job_id: str, task: Any) -> None:
    _update(job_id, _task=task, has_active_task=True)


def detach_task(job_id: str) -> Any | None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return None
        task = state.get("_task")
        state["_task"] = None
        state["has_active_task"] = False
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)
        return task


def get_task(job_id: str) -> Any | None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return None
        return state.get("_task")


def request_cancel(job_id: str) -> None:
    _update(job_id, cancel_requested=True)


def update_progress(
    job_id: str,
    *,
    stage: str | None = None,
    processed_count: int | None = None,
    analyzed_count: int | None = None,
) -> None:
    patch: dict[str, Any] = {}
    if stage is not None:
        patch["stage"] = stage
    if processed_count is not None:
        patch["processed_count"] = max(0, int(processed_count))
    if analyzed_count is not None:
        patch["analyzed_count"] = max(0, int(analyzed_count))
    if patch:
        _update(job_id, **patch)


def add_partial_analyses(
    job_id: str,
    analyses: dict[str, dict[str, Any]],
) -> None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        existing = dict(state.get("analyses") or {})
        existing.update(analyses)
        state["analyses"] = existing
        state["analyzed_count"] = sum(
            1 for v in existing.values()
            if isinstance(v, dict) and v.get("llm_score") is not None
        )
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)


def mark_done(
    job_id: str,
    *,
    processed_count: int,
    analyzed_count: int,
    processing_time_seconds: float,
) -> None:
    _update(
        job_id,
        status="done",
        stage="done",
        processed_count=max(0, int(processed_count)),
        analyzed_count=max(0, int(analyzed_count)),
        processing_time_seconds=round(float(processing_time_seconds), 3),
        error=None,
        cancel_requested=False,
        has_active_task=False,
        _task=None,
    )


def mark_failed(job_id: str, error: str) -> None:
    _update(
        job_id,
        status="error",
        stage="error",
        error=error.strip() or "Ошибка анализа",
        has_active_task=False,
        _task=None,
    )


def mark_cancelled(
    job_id: str,
    *,
    processing_time_seconds: float | None = None,
    error: str | None = None,
) -> None:
    patch: dict[str, Any] = {
        "status": "cancelled",
        "stage": "cancelled",
        "error": (error or "").strip() or "Операция отменена пользователем",
        "has_active_task": False,
        "_task": None,
    }
    if processing_time_seconds is not None:
        patch["processing_time_seconds"] = round(float(processing_time_seconds), 3)
    _update(job_id, **patch)
