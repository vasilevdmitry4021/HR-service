"""Разбор ответа pre-screening LLM (устойчивость к обёрткам и markdown)."""

from __future__ import annotations

from app.services import llm_prescoring


def test_parse_prescore_plain_array() -> None:
    raw = '[{"resume_id":"a","score":72},{"id":"b","llm_score":55}]'
    arr = llm_prescoring._parse_prescore_llm_text(raw)
    assert arr is not None
    assert len(arr) == 2


def test_parse_prescore_wrapped_object() -> None:
    raw = '{"results": [{"resume_id": "x", "score": 80}]}'
    arr = llm_prescoring._parse_prescore_llm_text(raw)
    assert arr is not None
    assert arr[0].get("score") == 80


def test_parse_prescore_markdown_fence() -> None:
    raw = '```json\n[{"resume_id":"r1","score":10}]\n```'
    arr = llm_prescoring._parse_prescore_llm_text(raw)
    assert arr is not None
    assert arr[0]["resume_id"] == "r1"


def test_parse_prescore_prefix_noise() -> None:
    raw = 'Here is JSON:\n[{"resume_id":"z","score":99}]\nThanks.'
    arr = llm_prescoring._parse_prescore_llm_text(raw)
    assert arr is not None
    assert arr[0]["score"] == 99


def test_scores_partial_array_maps_by_position() -> None:
    chunk = [
        {"id": "a", "hh_resume_id": "a"},
        {"id": "b", "hh_resume_id": "b"},
        {"id": "c", "hh_resume_id": "c"},
    ]
    arr = [{"score": 10}, {"score": 20}, {"score": 30}]

    def rid_of(r: dict) -> str:
        return str(r.get("id", ""))

    got = llm_prescoring._scores_from_array_for_chunk(arr, chunk, rid_of)
    assert got == {"a": 10, "b": 20, "c": 30}


def test_scores_shorter_array_prefix_only() -> None:
    chunk = [
        {"id": "a", "hh_resume_id": "a"},
        {"id": "b", "hh_resume_id": "b"},
    ]
    arr = [{"score": 55}]

    def rid_of(r: dict) -> str:
        return str(r.get("id", ""))

    got = llm_prescoring._scores_from_array_for_chunk(arr, chunk, rid_of)
    assert got == {"a": 55}
