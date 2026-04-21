from __future__ import annotations

from types import SimpleNamespace

from app.services import llm_prescoring


def _resume(rid: str) -> dict[str, str]:
    return {"id": rid, "hh_resume_id": rid, "title": f"Resume {rid}"}


def _setup_llm(monkeypatch, *, batch_size: int = 4) -> None:
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(
            endpoint="http://llm",
            fast_model="fast",
            model="base",
            llm_fast_batch_size=batch_size,
            prescore_mode="chat_legacy",
            rerank_endpoint="",
            rerank_model="rerank-model",
            rerank_timeout_seconds=30.0,
            rerank_batch_size=200,
        ),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", False)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_recovery_enabled", True)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_single_retry_max_attempts", 3)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_recovery_max_depth", 10)


def test_prescore_recovers_by_splitting_batches(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c"), _resume("d")]
    _setup_llm(monkeypatch, batch_size=4)

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, db
        if "depth=0 size=4" in batch_label:
            return ([{"resume_id": "a", "score": 11}, {"resume_id": "d", "score": 44}], 0, "parse-fail")
        if "depth=1 size=2" in batch_label:
            return ([{"resume_id": "b", "score": 22}, {"resume_id": "c", "score": 33}], 0, "parse-fail")
        return (None, 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch({}, resumes)

    assert scores == {"a": 11, "b": 22, "c": 33, "d": 44}
    assert stats["status"] == "done"
    assert stats["llm_only_complete"] is True
    assert stats["unresolved_count"] == 0
    assert stats["recovery_batches_total"] >= 1
    assert stats["llm_calls_refill"] >= 1


def test_prescore_single_resume_retry_limit_sets_unresolved(monkeypatch) -> None:
    resumes = [_resume("x")]
    _setup_llm(monkeypatch, batch_size=1)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_single_retry_max_attempts", 2)

    monkeypatch.setattr(
        llm_prescoring,
        "_fetch_prescore_array",
        lambda *args, **kwargs: (None, 0, "parse-fail"),
    )
    scores, stats = llm_prescoring.prescore_resumes_batch({}, resumes)

    assert scores == {}
    assert stats["status"] == "partial"
    assert stats["llm_only_complete"] is False
    assert stats["unresolved_count"] == 1
    assert stats["single_resume_fail_count"] == 1
    assert stats["single_resume_attempts_total"] == 2


def test_prescore_respects_phase_budget_and_returns_partial(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c")]
    _setup_llm(monkeypatch, batch_size=3)

    calls = {"n": 0}

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, batch_label, db
        calls["n"] += 1
        return ([{"resume_id": "a", "score": 10}], 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch({}, resumes, max_seconds=0.0, phase="interactive")

    assert scores == {}
    assert calls["n"] == 0
    assert stats["budget_exhausted"] is True
    assert stats["status"] == "partial"
    assert stats["unresolved_count"] == 3


def test_prescore_fallback_covers_all_resumes_on_empty_llm(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c")]
    _setup_llm(monkeypatch, batch_size=3)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", True)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_fallback_min_score", 15)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_fallback_max_score", 75)

    monkeypatch.setattr(
        llm_prescoring,
        "_fetch_prescore_array",
        lambda *args, **kwargs: (None, 0, "parse-fail"),
    )
    scores, stats = llm_prescoring.prescore_resumes_batch(
        {"skills": ["python"], "position_keywords": ["developer"]},
        resumes,
    )
    assert set(scores.keys()) == {"a", "b", "c"}
    assert all(isinstance(v, int) for v in scores.values())
    assert stats["llm_scored_count"] == 0
    assert stats["fallback_scored_count"] == 3
    assert stats["coverage_ratio"] == 1.0
    assert stats["llm_only_complete"] is True
    assert stats["unresolved_count"] == 0


def test_prescore_keeps_raw_llm_scores(monkeypatch) -> None:
    resumes = [_resume("fit"), _resume("miss")]
    _setup_llm(monkeypatch, batch_size=2)

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, batch_label, db
        return (
            [
                {"resume_id": "fit", "score": 30},
                {"resume_id": "miss", "score": 90},
            ],
            0,
            "parse-fail",
        )

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch({"skills": ["Python"]}, resumes)
    assert scores == {"fit": 30, "miss": 90}
    assert stats["status"] == "done"


def test_format_prescore_header_ignores_expanded_synonyms() -> None:
    requirements = {
        "position_keywords": ["Python Developer"],
        "skills": ["Python", "FastAPI"],
        "experience_years_min": 3,
        "region": "Москва",
        "expanded_synonyms": {
            "Python": ["питон", "py", "python3"],
            "FastAPI": ["fast api", "фаст-апи"],
        },
    }
    header = llm_prescoring._format_prescore_header(requirements)
    assert "synonyms_summary" not in header


def test_format_prescore_header_without_synonyms_field() -> None:
    requirements = {"position_keywords": ["Developer"], "skills": ["Python"]}
    header = llm_prescoring._format_prescore_header(requirements)
    assert "synonyms_summary" not in header


def test_prescore_rerank_maps_relevance_to_int_scores(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b")]
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(
            endpoint="http://llm",
            fast_model="fast",
            model="base",
            llm_fast_batch_size=2,
            prescore_mode="rerank",
            rerank_endpoint="http://rerank",
            rerank_model="rerank-model",
            rerank_timeout_seconds=30.0,
            rerank_batch_size=2,
        ),
    )
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "call_rerank",
        lambda query, documents, **kwargs: [
            {"index": 0, "relevance_score": 0.91},
            {"index": 1, "relevance_score": 0.34},
        ],
    )
    scores, stats = llm_prescoring.prescore_resumes_batch(
        {"skills": ["python"]},
        resumes,
    )
    assert scores == {"a": 91, "b": 34}
    assert stats["prescore_mode"] == "rerank"
    assert stats["rerank_calls_total"] == 1


def test_prescore_rerank_splits_batch_on_failure(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c"), _resume("d")]
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(
            endpoint="http://llm",
            fast_model="fast",
            model="base",
            llm_fast_batch_size=4,
            prescore_mode="rerank",
            rerank_endpoint="http://rerank",
            rerank_model="rerank-model",
            rerank_timeout_seconds=30.0,
            rerank_batch_size=4,
        ),
    )
    calls = {"n": 0}

    def fake_rerank(query, documents, **kwargs):
        _ = query, kwargs
        calls["n"] += 1
        if len(documents) >= 4:
            return None
        return [{"index": i, "relevance_score": 0.5 + i * 0.1} for i in range(len(documents))]

    monkeypatch.setattr(llm_prescoring.llm_client, "call_rerank", fake_rerank)
    scores, stats = llm_prescoring.prescore_resumes_batch(
        {"skills": ["python"]},
        resumes,
    )
    assert len(scores) == 4
    assert calls["n"] >= 3
    assert stats["prescore_mode"] == "rerank"
    assert stats["rerank_batch_split_count"] >= 1
