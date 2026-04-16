from __future__ import annotations

from app.services import analyze_progress


def test_analyze_progress_lifecycle() -> None:
    job_id = analyze_progress.create_job(
        user_id="u-1",
        snapshot_id="s-1",
        total_count=3,
    )
    analyze_progress.mark_running(job_id)
    analyze_progress.update_progress(
        job_id,
        stage="running",
        processed_count=2,
        analyzed_count=1,
    )
    analyze_progress.mark_done(
        job_id,
        processed_count=3,
        analyzed_count=2,
        processing_time_seconds=0.75,
    )
    state = analyze_progress.get_job(job_id)
    assert state is not None
    assert state["status"] == "done"
    assert state["stage"] == "done"
    assert state["total_count"] == 3
    assert state["processed_count"] == 3
    assert state["analyzed_count"] == 2
    assert state["processing_time_seconds"] == 0.75


def test_analyze_progress_failure() -> None:
    job_id = analyze_progress.create_job(
        user_id="u-2",
        snapshot_id="s-2",
        total_count=1,
    )
    analyze_progress.mark_failed(job_id, "boom")
    state = analyze_progress.get_job(job_id)
    assert state is not None
    assert state["status"] == "error"
    assert state["stage"] == "error"
    assert state["error"] == "boom"
