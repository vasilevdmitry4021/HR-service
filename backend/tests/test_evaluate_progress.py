from __future__ import annotations

from app.services import evaluate_progress


def test_mark_done_with_empty_scores_keeps_zero_coverage() -> None:
    job_id = evaluate_progress.create_job(
        user_id="u-1",
        snapshot_id="s-1",
        total_count=3,
    )
    evaluate_progress.mark_running(job_id)
    evaluate_progress.mark_done(
        job_id,
        scores={},
        processing_time_seconds=1.234,
        metrics={"status": "partial"},
    )

    state = evaluate_progress.get_job(job_id)
    assert state is not None
    assert state["status"] == "done"
    assert state["scored_count"] == 0
    assert state["completed_count"] == 0
    assert state["coverage_ratio"] == 0.0


def test_partial_scores_count_processed_ids_with_none_scores() -> None:
    job_id = evaluate_progress.create_job(
        user_id="u-2",
        snapshot_id="s-2",
        total_count=2,
    )

    evaluate_progress.add_partial_scores(
        job_id,
        {"r-1": None, "r-2": 70},
        phase="interactive",
        score_source="llm",
    )
    state = evaluate_progress.get_job(job_id)
    assert state is not None
    assert state["completed_count"] == 2
    assert state["interactive_done_count"] == 2
    assert state["interactive_llm_scored_count"] == 1
    assert state["scored_count"] == 1


def test_mark_failed_sets_failed_phase() -> None:
    job_id = evaluate_progress.create_job(
        user_id="u-3",
        snapshot_id="s-3",
        total_count=1,
    )
    evaluate_progress.mark_failed(job_id, "timeout")
    state = evaluate_progress.get_job(job_id)
    assert state is not None
    assert state["status"] == "error"
    assert state["stage"] == "error"
    assert state["phase"] == "error"
    assert state["error"] == "timeout"


def test_mark_done_keeps_zero_enrichment_metrics() -> None:
    job_id = evaluate_progress.create_job(
        user_id="u-4",
        snapshot_id="s-4",
        total_count=1,
    )
    evaluate_progress.mark_running(job_id)
    evaluate_progress.merge_metrics(
        job_id,
        {
            "cache_hit": 0,
            "cache_miss": 0,
            "hh_fetch_count": 0,
        },
    )
    evaluate_progress.mark_done(
        job_id,
        scores={"r-1": 75},
        processing_time_seconds=0.2,
        metrics={"status": "done"},
    )

    state = evaluate_progress.get_job(job_id)
    assert state is not None
    assert state["status"] == "done"
    assert state["metrics"]["cache_hit"] == 0
    assert state["metrics"]["cache_miss"] == 0
    assert state["metrics"]["hh_fetch_count"] == 0
