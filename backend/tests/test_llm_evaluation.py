from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services import llm_evaluation


@pytest.mark.asyncio
async def test_evaluate_all_resumes_passes_compact_prescore_payload_without_hh_fetch() -> None:
    resumes = [
        {
            "id": "resume-1",
            "hh_resume_id": "resume-1",
            "title": "Python Developer",
            "full_name": "Иван Тест",
            "age": 31,
            "experience_years": 6,
            "salary": {"amount": 300000, "currency": "RUR"},
            "skills": ["Python", "FastAPI"],
            "area": "Москва",
            "about": "Полное описание профиля, которое не должно идти в prescore.",
            "work_experience": [{"company": "ACME"}],
            "education": [{"summary": "ВУЗ"}],
        }
    ]
    parsed = {"text": "python developer", "skills": ["Python"]}
    captured_prescore_rows: list[dict[str, object]] = []

    def fake_prescore(requirements, rows, db=None, **kwargs):
        _ = requirements, db, kwargs
        captured_prescore_rows.extend(rows)
        return (
            {str(row.get("id")): 88 for row in rows},
            {
                "prescore_elapsed_ms": 5,
                "llm_calls_total": 1,
                "llm_calls_refill": 0,
                "avg_prompt_chars": 10,
                "parse_fail_count": 0,
                "refill_gain_ratio": 0.0,
                "budget_exhausted": False,
                "llm_scored_count": len(rows),
                "fallback_scored_count": 0,
                "coverage_ratio": 1.0,
            },
        )

    with patch(
        "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
        side_effect=fake_prescore,
    ):
        with patch(
            "app.services.llm_evaluation.hh_client.fetch_resume",
            new_callable=AsyncMock,
        ) as fetch_resume_mock:
            items, metrics = await llm_evaluation.evaluate_all_resumes(
                None,
                resumes,
                parsed,
                db=object(),
                user_id=uuid.uuid4(),
            )

    fetch_resume_mock.assert_not_awaited()
    assert len(captured_prescore_rows) == 1
    prescore_row = captured_prescore_rows[0]
    assert prescore_row["about"].startswith("Полное описание профиля")
    assert isinstance(prescore_row.get("work_experience"), list)
    assert prescore_row.get("semantic_summary")
    assert "education" not in prescore_row
    assert metrics["cache_hit"] == 0
    assert metrics["cache_miss"] == 0
    assert metrics["hh_fetch_count"] == 0
    assert items[0]["llm_score"] == 88


@pytest.mark.asyncio
async def test_evaluate_prescore_degrades_to_stub_if_enrichment_fails() -> None:
    resumes = [
        {
            "id": "resume-1",
            "hh_resume_id": "resume-1",
            "title": "Python Developer",
            "skills": ["Python"],
            "experience_years": 4,
        }
    ]
    parsed = {"text": "python developer", "skills": ["Python"]}
    captured_prescore_rows: list[dict[str, object]] = []

    def fake_prescore(requirements, rows, db=None, **kwargs):
        _ = requirements, db, kwargs
        captured_prescore_rows.extend(rows)
        return (
            {str(row.get("id")): 70 for row in rows},
            {
                "prescore_elapsed_ms": 5,
                "llm_calls_total": 1,
                "llm_calls_refill": 0,
                "avg_prompt_chars": 10,
                "parse_fail_count": 0,
                "refill_gain_ratio": 0.0,
                "budget_exhausted": False,
                "llm_scored_count": len(rows),
                "fallback_scored_count": 0,
                "coverage_ratio": 1.0,
            },
        )

    with patch(
        "app.services.llm_evaluation._enrich_resumes_for_llm",
        side_effect=RuntimeError("boom"),
    ):
        with patch(
            "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
            side_effect=fake_prescore,
        ):
            items, _metrics = await llm_evaluation.evaluate_all_resumes(
                "token",
                resumes,
                parsed,
                db=object(),
                user_id=uuid.uuid4(),
            )

    assert len(captured_prescore_rows) == 1
    prescore_row = captured_prescore_rows[0]
    assert prescore_row["id"] == "resume-1"
    assert prescore_row["title"] == "Python Developer"
    assert "about" not in prescore_row
    assert "work_experience" not in prescore_row
    assert "semantic_summary" not in prescore_row
    assert items[0]["llm_score"] == 70


@pytest.mark.asyncio
async def test_analyze_top_resumes_keeps_enrichment_for_top_n() -> None:
    user_id = str(uuid.uuid4())
    items = [
        {
            "id": "resume-top-1",
            "hh_resume_id": "resume-top-1",
            "title": "Senior Python",
            "skills": ["Python"],
            "llm_score": 95,
        },
        {
            "id": "resume-top-2",
            "hh_resume_id": "resume-top-2",
            "title": "Middle Python",
            "skills": ["Python"],
            "llm_score": 85,
        },
        {
            "id": "resume-low",
            "hh_resume_id": "resume-low",
            "title": "Junior QA",
            "skills": ["QA"],
            "llm_score": 40,
        },
    ]
    parsed = {"text": "python"}
    analyzed_chunks: list[list[dict[str, object]]] = []

    async def fake_fetch_resume(*args, **kwargs):
        _ = kwargs
        resume_id = str(args[1])
        return {
            "id": resume_id,
            "hh_resume_id": resume_id,
            "about": f"Полное резюме {resume_id}",
            "work_experience": [{"company": "ACME"}],
        }

    def fake_analyze_batch(parsed_params, chunk, **kwargs):
        _ = parsed_params, kwargs
        analyzed_chunks.append(chunk)
        return {
            str(row["id"]): {"llm_score": 90, "summary": f"analysis-{row['id']}"}
            for row in chunk
        }

    with patch(
        "app.services.llm_evaluation.llm_client.get_llm_config",
        return_value=SimpleNamespace(llm_detailed_top_n=2, llm_search_batch_size=10),
    ):
        with patch(
            "app.services.llm_evaluation.resume_cache.get_cached_resume",
            return_value=None,
        ):
            with patch("app.services.llm_evaluation.resume_cache.cache_resume"):
                with patch(
                    "app.services.llm_evaluation.hh_client.fetch_resume",
                    new_callable=AsyncMock,
                    side_effect=fake_fetch_resume,
                ) as fetch_resume_mock:
                    with patch(
                        "app.services.llm_evaluation.llm_resume_analyzer.analyze_resumes_batch",
                        side_effect=fake_analyze_batch,
                    ):
                        with patch(
                            "app.services.llm_evaluation.llm_analysis_cache.resume_lookup_keys",
                            return_value=[],
                        ):
                            with patch(
                                "app.services.llm_evaluation.llm_analysis_cache.store_for_resume_ids"
                            ):
                                out, metrics = await llm_evaluation.analyze_top_resumes(
                                    "token",
                                    items,
                                    parsed,
                                    user_id=user_id,
                                    query="python",
                                    top_n=2,
                                    db=object(),
                                )

    assert fetch_resume_mock.await_count == 2
    fetched_ids = {call.args[1] for call in fetch_resume_mock.await_args_list}
    assert fetched_ids == {"resume-top-1", "resume-top-2"}
    assert len(analyzed_chunks) == 1
    assert all(chunk_row.get("about") for chunk_row in analyzed_chunks[0])
    assert out[0]["llm_analysis"] is not None
    assert out[1]["llm_analysis"] is not None
    assert out[2].get("llm_analysis") is None
    assert metrics["detailed_batch_size"] == 10


@pytest.mark.asyncio
async def test_analyze_top_resumes_emits_per_item_progress_with_batch_3() -> None:
    user_id = str(uuid.uuid4())
    items = [
        {
            "id": f"resume-{i}",
            "hh_resume_id": f"resume-{i}",
            "title": "Python Developer",
            "skills": ["Python"],
            "llm_score": 100 - i,
            "about": f"about-{i}",
            "work_experience": [{"company": "ACME"}],
        }
        for i in range(15)
    ]
    parsed = {"text": "python"}
    analyze_calls: list[list[dict[str, Any]]] = []
    events: list[dict[str, Any]] = []

    async def fake_enrich(*args, **kwargs):
        _ = args, kwargs
        return items, {"cache_hit": 0, "cache_miss": 0, "hh_fetch_count": 0}

    def fake_analyze_batch(parsed_params, chunk, **kwargs):
        _ = parsed_params, kwargs
        analyze_calls.append(chunk)
        return {
            str(row["id"]): {
                "llm_score": int(row.get("llm_score") or 0),
                "summary": f"analysis-{row['id']}",
            }
            for row in chunk
        }

    with patch(
        "app.services.llm_evaluation.llm_client.get_llm_config",
        return_value=SimpleNamespace(llm_detailed_top_n=15, llm_search_batch_size=3),
    ):
        with patch(
            "app.services.llm_evaluation._enrich_resumes_for_llm",
            side_effect=fake_enrich,
        ):
            with patch(
                "app.services.llm_evaluation.llm_resume_analyzer.analyze_resumes_batch",
                side_effect=fake_analyze_batch,
            ):
                with patch(
                    "app.services.llm_evaluation.llm_analysis_cache.resume_lookup_keys",
                    return_value=[],
                ):
                    with patch(
                        "app.services.llm_evaluation.llm_analysis_cache.store_for_resume_ids"
                    ):
                        out, metrics = await llm_evaluation.analyze_top_resumes(
                            "token",
                            items,
                            parsed,
                            user_id=user_id,
                            query="python",
                            top_n=15,
                            db=object(),
                            progress_callback=lambda evt: events.append(dict(evt)),
                        )

    assert len(out) == 15
    assert len(analyze_calls) == 5
    assert all(len(chunk) == 3 for chunk in analyze_calls)
    analyzing_done_steps = [
        int(evt.get("phase_done_count") or 0)
        for evt in events
        if evt.get("phase") == "analyzing" and evt.get("stage") == "running"
    ]
    assert analyzing_done_steps == list(range(0, 16))
    assert events[-1].get("phase") == "done"
    assert events[-1].get("phase_done_count") == 1
    assert metrics["detailed_batch_count"] == 5


@pytest.mark.asyncio
async def test_evaluate_bonus_share_guard_in_final_top(monkeypatch) -> None:
    """Доля bonus в первых search_bonus_guard_top_n не превышает search_bonus_share_max."""
    guard_top_n = 10
    max_share = 0.2
    max_bonus = int(guard_top_n * max_share)

    monkeypatch.setattr(llm_evaluation.settings, "search_bonus_guard_top_n", guard_top_n)
    monkeypatch.setattr(llm_evaluation.settings, "search_bonus_share_max", max_share)

    resumes: list[dict[str, Any]] = []
    for i in range(15):
        resumes.append({
            "id": f"primary-{i}",
            "hh_resume_id": f"primary-{i}",
            "title": "Developer",
            "skills": ["Python"],
            "experience_years": 5,
            "match_source": "primary",
        })
    for i in range(8):
        resumes.append({
            "id": f"bonus-{i}",
            "hh_resume_id": f"bonus-{i}",
            "title": "Creative coder",
            "skills": ["Design"],
            "experience_years": 8,
            "match_source": "bonus",
        })

    parsed = {"text": "python developer", "skills": ["Python"]}

    def fake_prescore(requirements, rows, db=None, **kwargs):
        scores = {}
        for row in rows:
            rid = str(row.get("id"))
            if rid.startswith("bonus"):
                scores[rid] = 95
            else:
                scores[rid] = 60
        return scores, {
            "prescore_elapsed_ms": 1,
            "llm_calls_total": 1,
            "llm_calls_refill": 0,
            "avg_prompt_chars": 10,
            "parse_fail_count": 0,
            "refill_gain_ratio": 0.0,
            "budget_exhausted": False,
            "llm_scored_count": len(rows),
            "fallback_scored_count": 0,
            "coverage_ratio": 1.0,
        }

    with patch(
        "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
        side_effect=fake_prescore,
    ):
        items, metrics = await llm_evaluation.evaluate_all_resumes(
            None,
            resumes,
            parsed,
            db=object(),
            user_id=uuid.uuid4(),
        )

    top_n = items[:guard_top_n]
    bonus_in_top = sum(1 for x in top_n if x.get("match_source") == "bonus")
    assert bonus_in_top <= max_bonus, (
        f"bonus_in_top={bonus_in_top} > max_bonus={max_bonus} "
        f"(guard_top_n={guard_top_n}, max_share={max_share})"
    )
    total_bonus = sum(1 for x in items if x.get("match_source") == "bonus")
    assert total_bonus == 8


@pytest.mark.asyncio
async def test_evaluate_bonus_overflow_pushes_below_topn(monkeypatch) -> None:
    """Bonus-кандидаты с высокими LLM-оценками выталкиваются за пределы guard top-N,
    не превышая max share. Primary с низкими оценками остаются в top-N."""
    guard_top_n = 5
    max_share = 0.2
    max_bonus_in_top = int(guard_top_n * max_share)

    monkeypatch.setattr(llm_evaluation.settings, "search_bonus_guard_top_n", guard_top_n)
    monkeypatch.setattr(llm_evaluation.settings, "search_bonus_share_max", max_share)

    resumes: list[dict[str, Any]] = []
    for i in range(10):
        resumes.append({
            "id": f"primary-{i}",
            "hh_resume_id": f"primary-{i}",
            "title": "Developer",
            "skills": ["Python"],
            "experience_years": 3,
            "match_source": "primary",
        })
    for i in range(5):
        resumes.append({
            "id": f"bonus-{i}",
            "hh_resume_id": f"bonus-{i}",
            "title": "Creative",
            "skills": [],
            "experience_years": 10,
            "match_source": "bonus",
        })

    parsed = {"text": "python", "skills": ["Python"], "position_keywords": ["Developer"]}

    def fake_prescore(requirements, rows, db=None, **kwargs):
        scores = {}
        for row in rows:
            rid = str(row.get("id"))
            scores[rid] = 99 if rid.startswith("bonus") else 40
        return scores, {
            "prescore_elapsed_ms": 1,
            "llm_calls_total": 1,
            "llm_calls_refill": 0,
            "avg_prompt_chars": 10,
            "parse_fail_count": 0,
            "refill_gain_ratio": 0.0,
            "budget_exhausted": False,
            "llm_scored_count": len(rows),
            "fallback_scored_count": 0,
            "coverage_ratio": 1.0,
        }

    with patch(
        "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
        side_effect=fake_prescore,
    ):
        items, _metrics = await llm_evaluation.evaluate_all_resumes(
            None,
            resumes,
            parsed,
            db=object(),
            user_id=uuid.uuid4(),
        )

    top_n_items = items[:guard_top_n]
    bonus_in_top = sum(1 for x in top_n_items if x.get("match_source") == "bonus")
    assert bonus_in_top <= max_bonus_in_top, (
        f"leakage: bonus_in_top={bonus_in_top} > max_bonus={max_bonus_in_top}"
    )
    all_bonus = [x for x in items if x.get("match_source") == "bonus"]
    assert len(all_bonus) == 5, "все bonus-кандидаты должны присутствовать в результатах"
    overflow_bonus = [x for x in items[guard_top_n:] if x.get("match_source") == "bonus"]
    assert len(overflow_bonus) >= 5 - max_bonus_in_top


def test_simple_sort_does_not_promote_bonus_without_must_skills() -> None:
    resumes = [
        {
            "id": "primary-ok",
            "title": "Java Developer",
            "skills": ["Java", "Spring"],
            "experience_years": 4,
            "match_source": "primary",
        },
        {
            "id": "bonus-weak",
            "title": "Creative coder",
            "skills": ["Design"],
            "about": "вайбкодинг и AI pair",
            "experience_years": 8,
            "match_source": "bonus",
        },
    ]
    parsed = {
        "skills": ["Java"],
        "position_keywords": ["developer"],
        "soft_signals": ["вайбкодинг", "ai pair"],
    }
    sorted_rows = llm_evaluation._sort_by_simple_criteria(resumes, parsed)
    assert sorted_rows[0]["id"] == "primary-ok"


@pytest.mark.asyncio
async def test_evaluate_all_resumes_sets_partial_on_unresolved(monkeypatch) -> None:
    resumes = [
        {"id": "r1", "hh_resume_id": "r1", "title": "A", "skills": ["Python"], "experience_years": 3},
        {"id": "r2", "hh_resume_id": "r2", "title": "B", "skills": ["Python"], "experience_years": 3},
    ]
    parsed = {"text": "python", "skills": ["Python"]}
    monkeypatch.setattr(llm_evaluation.settings, "evaluate_interactive_top_n", 2)

    def fake_prescore(requirements, rows, db=None, **kwargs):
        _ = requirements, db, kwargs
        return {"r1": 80}, {
            "prescore_elapsed_ms": 1,
            "llm_calls_total": 1,
            "llm_calls_refill": 1,
            "avg_prompt_chars": 10,
            "parse_fail_count": 1,
            "refill_gain_ratio": 0.0,
            "budget_exhausted": False,
            "llm_scored_count": 1,
            "fallback_scored_count": 0,
            "coverage_ratio": 0.5,
            "unresolved_count": 1,
            "recovery_batches_total": 1,
            "single_resume_attempts_total": 2,
            "single_resume_fail_count": 1,
            "llm_only_complete": False,
            "status": "partial",
        }

    with patch(
        "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
        side_effect=fake_prescore,
    ):
        items, metrics = await llm_evaluation.evaluate_all_resumes(
            None,
            resumes,
            parsed,
            db=object(),
            user_id=uuid.uuid4(),
        )

    assert len(items) == 2
    assert metrics["status"] == "partial"
    assert metrics["llm_only_complete"] is False
    assert metrics["unresolved_count"] == 1


@pytest.mark.asyncio
async def test_evaluate_all_resumes_sets_error_when_no_scores(monkeypatch) -> None:
    resumes = [
        {"id": "r1", "hh_resume_id": "r1", "title": "A", "skills": ["Python"], "experience_years": 3},
    ]
    parsed = {"text": "python", "skills": ["Python"]}
    monkeypatch.setattr(llm_evaluation.settings, "evaluate_interactive_top_n", 1)

    def fake_prescore(requirements, rows, db=None, **kwargs):
        _ = requirements, rows, db, kwargs
        return {}, {
            "prescore_elapsed_ms": 1,
            "llm_calls_total": 1,
            "llm_calls_refill": 1,
            "avg_prompt_chars": 10,
            "parse_fail_count": 1,
            "refill_gain_ratio": 0.0,
            "budget_exhausted": False,
            "llm_scored_count": 0,
            "fallback_scored_count": 0,
            "coverage_ratio": 0.0,
            "unresolved_count": 1,
            "recovery_batches_total": 1,
            "single_resume_attempts_total": 3,
            "single_resume_fail_count": 1,
            "llm_only_complete": False,
            "status": "error",
        }

    with patch(
        "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
        side_effect=fake_prescore,
    ):
        _items, metrics = await llm_evaluation.evaluate_all_resumes(
            None,
            resumes,
            parsed,
            db=object(),
            user_id=uuid.uuid4(),
        )

    assert metrics["status"] == "error"
    assert metrics["unresolved_count"] == 1


@pytest.mark.asyncio
async def test_evaluate_exposes_rerank_metrics(monkeypatch) -> None:
    resumes = [
        {"id": "r1", "hh_resume_id": "r1", "title": "A", "skills": ["Python"], "experience_years": 3},
        {"id": "r2", "hh_resume_id": "r2", "title": "B", "skills": ["Python"], "experience_years": 4},
    ]
    parsed = {"text": "python", "skills": ["Python"]}
    monkeypatch.setattr(llm_evaluation.settings, "evaluate_interactive_top_n", 2)

    def fake_prescore(requirements, rows, db=None, **kwargs):
        _ = requirements, db, kwargs
        return {"r1": 91, "r2": 64}, {
            "prescore_elapsed_ms": 1,
            "llm_calls_total": 2,
            "llm_calls_refill": 0,
            "avg_prompt_chars": 0,
            "parse_fail_count": 0,
            "refill_gain_ratio": 0.0,
            "budget_exhausted": False,
            "llm_scored_count": 2,
            "fallback_scored_count": 0,
            "coverage_ratio": 1.0,
            "unresolved_count": 0,
            "recovery_batches_total": 1,
            "single_resume_attempts_total": 0,
            "single_resume_fail_count": 0,
            "llm_only_complete": True,
            "status": "done",
            "prescore_mode": "rerank",
            "rerank_calls_total": 2,
            "rerank_batch_split_count": 1,
            "rerank_avg_score": 77.5,
            "rerank_raw_avg_relevance": 0.775,
        }

    with patch(
        "app.services.llm_evaluation.llm_prescoring.prescore_resumes_batch",
        side_effect=fake_prescore,
    ):
        _items, metrics = await llm_evaluation.evaluate_all_resumes(
            None,
            resumes,
            parsed,
            db=object(),
            user_id=uuid.uuid4(),
        )

    assert metrics["prescore_mode"] == "rerank"
    assert metrics["rerank_calls_total"] == 2
    assert metrics["rerank_batch_split_count"] == 1
