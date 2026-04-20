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
        "total_count": max(0, int(total_count)),
        "scored_count": 0,
        "completed_count": 0,
        "llm_scored_count": 0,
        "fallback_scored_count": 0,
        "coverage_ratio": 0.0,
        "llm_coverage_ratio": 0.0,
        "unresolved_count": max(0, int(total_count)),
        "llm_only_complete": False,
        "phase": "interactive",
        "interactive_total_count": 0,
        "background_total_count": 0,
        "interactive_done_count": 0,
        "background_done_count": 0,
        "interactive_llm_scored_count": 0,
        "background_llm_scored_count": 0,
        "interactive_fallback_count": 0,
        "background_fallback_count": 0,
        "stage": "queued",
        "processing_time_seconds": None,
        "error": None,
        "metrics": {},
        "scores": {},
        "_interactive_scored_ids": set(),
        "_background_scored_ids": set(),
        "_interactive_llm_scored_ids": set(),
        "_background_llm_scored_ids": set(),
        "_interactive_fallback_scored_ids": set(),
        "_background_fallback_scored_ids": set(),
        "created_monotonic": now,
        "updated_monotonic": now,
    }
    with _lock:
        _jobs.set(job_id, payload)
    return job_id


def get_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        item = _jobs.get(job_id)
        return dict(item) if item else None


def _update(job_id: str, **changes: Any) -> None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        state.update(changes)
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)


def mark_running(job_id: str) -> None:
    _update(job_id, status="running", stage="preparing", phase="interactive")


def update_stage(job_id: str, stage: str) -> None:
    _update(job_id, stage=stage)


def update_phase(job_id: str, phase: str) -> None:
    _update(job_id, phase=phase)


def merge_metrics(job_id: str, patch: dict[str, Any]) -> None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        metrics = dict(state.get("metrics") or {})
        metrics.update({k: v for k, v in patch.items() if k})
        state["metrics"] = metrics
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)


def add_partial_scores(
    job_id: str,
    scores: dict[str, int | None],
    *,
    phase: str | None = None,
    score_source: str = "llm",
) -> None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        existing = dict(state.get("scores") or {})
        existing.update(scores)
        state["scores"] = existing
        scored_ids = {rid for rid, score in existing.items() if isinstance(score, int)}
        state["scored_count"] = len(scored_ids)
        state["completed_count"] = len(existing)
        total = max(0, int(state.get("total_count") or 0))
        state["coverage_ratio"] = round((len(scored_ids) / total), 4) if total > 0 else 1.0
        state["llm_coverage_ratio"] = state["coverage_ratio"]
        state["unresolved_count"] = max(0, total - len(scored_ids))
        state["llm_only_complete"] = bool((state["unresolved_count"] or 0) == 0)
        phase_ids = {rid for rid in scores.keys() if rid}
        phase_scored_ids = {rid for rid, score in scores.items() if rid and isinstance(score, int)}
        if phase == "interactive":
            seen = set(state.get("_interactive_scored_ids") or set())
            seen.update(phase_ids)
            state["_interactive_scored_ids"] = seen
            state["interactive_done_count"] = len(seen)
            if score_source == "fallback":
                f_seen = set(state.get("_interactive_fallback_scored_ids") or set())
                f_seen.update(phase_scored_ids)
                state["_interactive_fallback_scored_ids"] = f_seen
                state["interactive_fallback_count"] = len(f_seen)
            else:
                l_seen = set(state.get("_interactive_llm_scored_ids") or set())
                l_seen.update(phase_scored_ids)
                state["_interactive_llm_scored_ids"] = l_seen
                state["interactive_llm_scored_count"] = len(l_seen)
        elif phase == "background":
            seen = set(state.get("_background_scored_ids") or set())
            seen.update(phase_ids)
            state["_background_scored_ids"] = seen
            state["background_done_count"] = len(seen)
            if score_source == "fallback":
                f_seen = set(state.get("_background_fallback_scored_ids") or set())
                f_seen.update(phase_scored_ids)
                state["_background_fallback_scored_ids"] = f_seen
                state["background_fallback_count"] = len(f_seen)
            else:
                l_seen = set(state.get("_background_llm_scored_ids") or set())
                l_seen.update(phase_scored_ids)
                state["_background_llm_scored_ids"] = l_seen
                state["background_llm_scored_count"] = len(l_seen)
        state["llm_scored_count"] = int(state.get("interactive_llm_scored_count") or 0) + int(
            state.get("background_llm_scored_count") or 0
        )
        state["fallback_scored_count"] = int(state.get("interactive_fallback_count") or 0) + int(
            state.get("background_fallback_count") or 0
        )
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)


def update_counters(
    job_id: str,
    *,
    total_count: int | None = None,
    interactive_total_count: int | None = None,
    background_total_count: int | None = None,
) -> None:
    with _lock:
        state = _jobs.get(job_id)
        if not state:
            return
        if total_count is not None:
            state["total_count"] = max(0, int(total_count))
        if interactive_total_count is not None:
            state["interactive_total_count"] = max(0, int(interactive_total_count))
        if background_total_count is not None:
            state["background_total_count"] = max(0, int(background_total_count))
        state["updated_monotonic"] = time.monotonic()
        _jobs.set(job_id, state)


def mark_done(
    job_id: str,
    *,
    scores: dict[str, int | None],
    processing_time_seconds: float,
    metrics: dict[str, Any],
) -> None:
    state = get_job(job_id) or {}
    scored_count = sum(1 for score in scores.values() if isinstance(score, int))
    total_count = max(0, int(state.get("total_count") or len(scores)))
    metrics_current = dict(state.get("metrics") or {})
    metrics_final = {**metrics_current, **dict(metrics)}
    completed_count = max(int(state.get("completed_count") or 0), len(scores))
    _update(
        job_id,
        status="done",
        stage="done",
        phase="done",
        scores=dict(scores),
        scored_count=scored_count,
        completed_count=completed_count,
        llm_scored_count=int(state.get("llm_scored_count") or 0),
        fallback_scored_count=int(state.get("fallback_scored_count") or 0),
        coverage_ratio=round((scored_count / total_count), 4) if total_count > 0 else 1.0,
        llm_coverage_ratio=round((scored_count / total_count), 4) if total_count > 0 else 1.0,
        unresolved_count=max(0, total_count - scored_count),
        llm_only_complete=max(0, total_count - scored_count) == 0,
        interactive_done_count=int(state.get("interactive_done_count") or 0),
        background_done_count=int(state.get("background_done_count") or 0),
        interactive_llm_scored_count=int(state.get("interactive_llm_scored_count") or 0),
        background_llm_scored_count=int(state.get("background_llm_scored_count") or 0),
        interactive_fallback_count=int(state.get("interactive_fallback_count") or 0),
        background_fallback_count=int(state.get("background_fallback_count") or 0),
        processing_time_seconds=round(float(processing_time_seconds), 3),
        metrics=metrics_final,
        error=None,
    )


def mark_partial(
    job_id: str,
    *,
    scores: dict[str, int | None],
    processing_time_seconds: float,
    metrics: dict[str, Any],
    error: str | None = None,
) -> None:
    state = get_job(job_id) or {}
    scored_count = sum(1 for score in scores.values() if isinstance(score, int))
    total_count = max(0, int(state.get("total_count") or len(scores)))
    unresolved_count = max(0, int(metrics.get("unresolved_count") or (total_count - scored_count)))
    metrics_current = dict(state.get("metrics") or {})
    metrics_final = {**metrics_current, **dict(metrics)}
    completed_count = max(int(state.get("completed_count") or 0), len(scores))
    _update(
        job_id,
        status="partial",
        stage="partial",
        phase="done",
        scores=dict(scores),
        scored_count=scored_count,
        completed_count=completed_count,
        llm_scored_count=int(state.get("llm_scored_count") or scored_count),
        fallback_scored_count=int(state.get("fallback_scored_count") or 0),
        coverage_ratio=round((scored_count / total_count), 4) if total_count > 0 else 1.0,
        llm_coverage_ratio=round((scored_count / total_count), 4) if total_count > 0 else 1.0,
        unresolved_count=unresolved_count,
        llm_only_complete=False,
        interactive_done_count=int(state.get("interactive_done_count") or 0),
        background_done_count=int(state.get("background_done_count") or 0),
        interactive_llm_scored_count=int(state.get("interactive_llm_scored_count") or 0),
        background_llm_scored_count=int(state.get("background_llm_scored_count") or 0),
        interactive_fallback_count=int(state.get("interactive_fallback_count") or 0),
        background_fallback_count=int(state.get("background_fallback_count") or 0),
        processing_time_seconds=round(float(processing_time_seconds), 3),
        metrics=metrics_final,
        error=(error or "").strip() or None,
    )


def mark_failed(job_id: str, error: str) -> None:
    _update(
        job_id,
        status="error",
        stage="error",
        phase="error",
        error=error.strip() or "Ошибка оценки",
    )
