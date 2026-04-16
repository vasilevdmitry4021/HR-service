from __future__ import annotations

from types import SimpleNamespace

from app.services import llm_prescoring


def _resume(rid: str) -> dict[str, str]:
    return {"id": rid, "hh_resume_id": rid, "title": f"Resume {rid}"}


def test_prescore_refill_by_minibatches(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c"), _resume("d"), _resume("e")]
    calls: list[str] = []

    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=5),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", True)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_max_llm_calls", 10)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_batch_size", 2)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_max_seconds", 30.0)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", True)

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, db
        calls.append(batch_label)
        if batch_label.startswith("батч"):
            # Частичный batched-ответ: оценка только для части резюме.
            return (
                [
                    {"resume_id": "a", "score": 11},
                    {"resume_id": "c", "score": 33},
                ],
                0,
                "parse-fail",
            )
        if batch_label.startswith("refill 1"):
            return (
                [
                    {"resume_id": "b", "score": 22},
                    {"resume_id": "d", "score": 44},
                ],
                0,
                "parse-fail",
            )
        if batch_label.startswith("refill 2"):
            return ([{"resume_id": "e", "score": 55}], 0, "parse-fail")
        return (None, 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch({}, resumes)

    assert scores == {"a": 11, "b": 22, "c": 33, "d": 44, "e": 55}
    assert stats["llm_calls_total"] == 3
    assert stats["llm_calls_refill"] == 2
    assert any(x.startswith("refill 1") for x in calls)
    assert any(x.startswith("refill 2") for x in calls)
    assert stats["llm_scored_count"] == 5
    assert stats["fallback_scored_count"] == 0
    assert stats["coverage_ratio"] == 1.0


def test_prescore_refill_respects_max_calls(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c")]

    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=3),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", True)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_max_llm_calls", 1)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_batch_size", 2)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_max_seconds", 30.0)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", False)

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, db, batch_label
        # Первый батч не даёт оценок, refill даёт только одну — дальше лимит вызовов исчерпан.
        if "батч" in batch_label:
            return ([], 0, "parse-fail")
        return ([{"resume_id": "a", "score": 10}], 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch({}, resumes)

    assert scores == {"a": 10}
    assert stats["llm_calls_refill"] == 1
    assert stats["llm_calls_total"] == 2


def test_prescore_adapts_batch_size_on_high_missing(monkeypatch) -> None:
    resumes = [_resume(str(i)) for i in range(10)]
    labels: list[str] = []

    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=4),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", False)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", False)

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, db
        labels.append(batch_label)
        if "0..3" in batch_label:
            # Очень высокий missing -> ожидаем снижение batch size.
            return ([{"resume_id": "0", "score": 10}], 0, "parse-fail")
        return ([{"resume_id": str(i), "score": 50} for i in range(10)], 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    llm_prescoring.prescore_resumes_batch({}, resumes)

    assert len(labels) == 4


def test_prescore_stops_refill_when_gain_low(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c"), _resume("d"), _resume("e")]
    labels: list[str] = []

    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=5),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", True)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_max_llm_calls", 50)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_batch_size", 2)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_max_seconds", 30.0)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_min_gain", 2)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", False)

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, db
        labels.append(batch_label)
        if batch_label.startswith("батч"):
            return ([{"resume_id": "a", "score": 11}], 0, "parse-fail")
        # На refill каждый раз прирост только 1 — после 3 циклов должно остановиться.
        if "refill 1" in batch_label:
            return ([{"resume_id": "b", "score": 22}], 0, "parse-fail")
        if "refill 2" in batch_label:
            return ([{"resume_id": "c", "score": 33}], 0, "parse-fail")
        if "refill 3" in batch_label:
            return ([{"resume_id": "d", "score": 44}], 0, "parse-fail")
        return ([{"resume_id": "e", "score": 55}], 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch({}, resumes)

    assert "e" not in scores
    assert stats["llm_calls_refill"] == 3
    assert stats["refill_gain_ratio"] > 0


def test_prescore_respects_phase_budget(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c")]

    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=3),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", False)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", False)

    calls = {"n": 0}

    def fake_fetch(prompt: str, model: str, *, batch_label: str, db=None):
        _ = prompt, model, batch_label, db
        calls["n"] += 1
        return ([{"resume_id": "a", "score": 10}], 0, "parse-fail")

    monkeypatch.setattr(llm_prescoring, "_fetch_prescore_array", fake_fetch)
    scores, stats = llm_prescoring.prescore_resumes_batch(
        {},
        resumes,
        max_seconds=0.0,
        phase="interactive",
    )

    assert scores == {}
    assert calls["n"] == 0
    assert stats["budget_exhausted"] is True


def test_prescore_fallback_covers_all_resumes_on_empty_llm(monkeypatch) -> None:
    resumes = [_resume("a"), _resume("b"), _resume("c")]
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=3),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", False)
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


def test_prescore_fallback_score_respects_range(monkeypatch) -> None:
    resumes = [{"id": "x", "skills": [], "title": "", "experience_years": None, "area": ""}]
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=1),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", False)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", True)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_fallback_min_score", 31)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_fallback_max_score", 32)
    monkeypatch.setattr(
        llm_prescoring,
        "_fetch_prescore_array",
        lambda *args, **kwargs: (None, 0, "timeout"),
    )
    scores, _stats = llm_prescoring.prescore_resumes_batch({}, resumes)
    assert scores["x"] in (31, 32)


def test_prescore_fallback_is_deterministic(monkeypatch) -> None:
    resumes = [
        {
            "id": "same",
            "skills": ["python", "sql"],
            "title": "Python Developer",
            "experience_years": 4,
            "area": "Москва",
        }
    ]
    req = {
        "skills": ["python", "sql", "fastapi"],
        "position_keywords": ["developer"],
        "experience_years_min": 3,
        "region": "Москва",
    }
    monkeypatch.setattr(
        llm_prescoring.llm_client,
        "get_llm_config",
        lambda _db: SimpleNamespace(endpoint="http://llm", fast_model="fast", model="base", llm_fast_batch_size=1),
    )
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_refill_enabled", False)
    monkeypatch.setattr(llm_prescoring.settings, "llm_prescore_enable_fallback", True)
    monkeypatch.setattr(
        llm_prescoring,
        "_fetch_prescore_array",
        lambda *args, **kwargs: (None, 0, "parse-fail"),
    )

    score1, _ = llm_prescoring.prescore_resumes_batch(req, resumes)
    score2, _ = llm_prescoring.prescore_resumes_batch(req, resumes)
    assert score1["same"] == score2["same"]
