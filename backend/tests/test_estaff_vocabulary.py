from __future__ import annotations

from app.services.estaff_vocabulary import (
    normalize_vocab_label,
    parse_get_voc_response,
    resolve_vocab_id,
)


def test_parse_get_voc_response_dynamic_key() -> None:
    items = parse_get_voc_response(
        {
            "success": True,
            "locations": [
                {"id": 1, "name": "Москва"},
                {"id": 2, "name": "Тверь"},
            ],
        },
    )
    assert len(items) == 2
    assert items[0]["id"] == 1


def test_parse_get_voc_response_success_false() -> None:
    assert parse_get_voc_response({"success": False, "x": [{"id": 1}]}) == []


def test_normalize_vocab_label_strips_city_prefix() -> None:
    assert normalize_vocab_label("г. Москва") == "москва"


def test_resolve_vocab_id_exact() -> None:
    items = [{"id": 10, "name": "Python"}, {"id": 11, "name": "Java"}]
    r = resolve_vocab_id(items, "python", field_name="t")
    assert r.id == "10"
    assert r.reason is None


def test_resolve_vocab_id_ambiguous() -> None:
    items = [{"id": 1, "name": "Тест А"}, {"id": 2, "name": "Тест Б"}]
    r = resolve_vocab_id(items, "Тест", field_name="t", allow_prefix=True)
    assert r.id is None
    assert r.reason == "ambiguous"


def test_resolve_vocab_id_not_found() -> None:
    r = resolve_vocab_id([{"id": 1, "name": "А"}], "Б", field_name="t")
    assert r.id is None
    assert r.reason == "not_found"
