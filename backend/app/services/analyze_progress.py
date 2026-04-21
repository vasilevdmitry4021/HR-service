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


def _clamp_ratio(done: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, float(done) / float(total)))


def _compute_progress_percent(phase: str, phase_done_count: int, phase_total_count: int) -> float:
    ratio = _clamp_ratio(phase_done_count, phase_total_count)
    if phase == "done":
        return 100.0
    if phase == "enriching":
        return 30.0 * ratio
    if phase == "analyzing":
        return 30.0 + (65.0 * ratio)
    if phase == "finalizing":
        return 95.0
    return 0.0


def create_job(*, user_id: str, snapshot_id: str, total_count: int) -> str:
    job_id = str(uuid.uuid4())
    now = time.monotonic()
    payload: dict[str, Any] = {
        "job_id": job_id,
        "user_id": user_id,
        "snapshot_id": snapshot_id,
        "status": "queued",
        "stage": "queued",
        "phase": "queued",
        "total_count": max(0, int(total_count)),
        "processed_count": 0,
        "analyzed_count": 0,
        "phase_total_count": 0,
        "phase_done_count": 0,
        "enriched_count": 0,
        "progress_percent": 0.0,
        "analyses": {},
        "metrics": {},
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
    _update(
        job_id,
        status="running",
        stage="preparing",
        phase="enriching",
        phase_done_count=0,
        progress_percent=0.0,
    )


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
    phase: str | None = None,
    phase_total_count: int | None = None,
    phase_done_count: int | None = None,
    enriched_count: int | None = None,
    progress_percent: float | None = None,
) -> None:
    patch: dict[str, Any] = {}
    if stage is not None:
        patch["stage"] = stage
    if processed_count is not None:
        patch["processed_count"] = max(0, int(processed_count))
    if analyzed_count is not None:
        patch["analyzed_count"] = max(0, int(analyzed_count))
    if phase is not None:
        patch["phase"] = phase
    if phase_total_count is not None:
        patch["phase_total_count"] = max(0, int(phase_total_count))
    if phase_done_count is not None:
        patch["phase_done_count"] = max(0, int(phase_done_count))
    if enriched_count is not None:
        patch["enriched_count"] = max(0, int(enriched_count))
    if progress_percent is not None:
        patch["progress_percent"] = round(max(0.0, min(100.0, float(progress_percent))), 2)
    elif (
        patch.get("phase") is not None
        or patch.get("phase_total_count") is not None
        or patch.get("phase_done_count") is not None
    ):
        phase_for_percent = str(patch.get("phase") or "queued")
        total_for_percent = int(patch.get("phase_total_count") or 0)
        done_for_percent = int(patch.get("phase_done_count") or 0)
        patch["progress_percent"] = round(
            _compute_progress_percent(phase_for_percent, done_for_percent, total_for_percent),
            2,
        )
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
    metrics: dict[str, Any] | None = None,
) -> None:
    _update(
        job_id,
        status="done",
        stage="done",
        phase="done",
        processed_count=max(0, int(processed_count)),
        analyzed_count=max(0, int(analyzed_count)),
        phase_total_count=1,
        phase_done_count=1,
        enriched_count=max(0, int(processed_count)),
        progress_percent=100.0,
        processing_time_seconds=round(float(processing_time_seconds), 3),
        error=None,
        cancel_requested=False,
        has_active_task=False,
        _task=None,
    )
    if metrics:
        merge_metrics(job_id, metrics)


def mark_failed(job_id: str, error: str) -> None:
    _update(
        job_id,
        status="error",
        stage="error",
        phase="error",
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
        "phase": "cancelled",
        "error": (error or "").strip() or "Операция отменена пользователем",
        "has_active_task": False,
        "_task": None,
    }
    if processing_time_seconds is not None:
        patch["processing_time_seconds"] = round(float(processing_time_seconds), 3)
    _update(job_id, **patch)


def merge_metrics(job_id: str, patch: dict[str, Any] | None) -> None:
    if not patch:
        return
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        existing = dict(state.get("metrics") or {})
        for key, value in patch.items():
            existing[str(key)] = value
        state["metrics"] = existing
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)
