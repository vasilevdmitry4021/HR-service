from __future__ import annotations

from app.services import llm_client


def test_normalize_llm_output_v2_fields() -> None:
    raw = {
        "must_position": ["System Analyst", "Системный аналитик"],
        "must_skills": [
            {
                "canonical": "microservices",
                "synonyms": ["микросервисы", "micro-service"],
                "intent_strength": "required",
                "query_confidence": 0.9,
            },
        ],
        "should_skills": [
            {
                "canonical": "Cursor",
                "synonyms": ["AI pair"],
                "intent_strength": "preferred",
                "query_confidence": 0.6,
            },
        ],
        "soft_signals": ["вайбкодинг"],
    }
    out = llm_client._normalize_llm_output(raw)
    assert out["must_position"] == ["System Analyst", "Системный аналитик"]
    assert out["must_skills"][0]["canonical"] == "microservices"
    assert out["must_skills"][0]["intent_strength"] == "required"
    assert out["should_skills"][0]["canonical"] == "Cursor"
    assert out["should_skills"][0]["intent_strength"] == "preferred"
    assert out["soft_signals"] == ["вайбкодинг"]
    assert "microservices" in out["skills"]


def test_normalize_llm_output_backward_compatible() -> None:
    raw = {
        "skills": ["Python", "FastAPI"],
        "position_keywords": ["backend developer"],
        "experience_years_min": 3,
    }
    out = llm_client._normalize_llm_output(raw)
    assert out["skills"] == ["Python", "FastAPI"]
    assert out["must_position"] == ["backend developer"]
    assert out["must_skills"] == [
        {"canonical": "Python", "synonyms": []},
        {"canonical": "FastAPI", "synonyms": []},
    ]
    assert out["risky_demoted_to_should"] == 0


def test_normalize_llm_output_demotes_jargon_from_must() -> None:
    raw = {
        "must_skills": [
            {"canonical": "Python", "synonyms": ["Py"]},
            {"canonical": "вайбкодинг", "synonyms": ["vibe coding"]},
        ],
        "soft_signals": [],
    }
    out = llm_client._normalize_llm_output(raw)
    must = [x["canonical"] for x in out["must_skills"]]
    should = [x["canonical"] for x in out["should_skills"]]
    assert "Python" in must
    assert "вайбкодинг" not in must
    assert "вайбкодинг" in should
    assert "вайбкодинг" in out["risky_skills"]
    assert out["risky_demoted_to_should"] >= 1


def test_normalize_llm_output_uses_semantic_skills_contract() -> None:
    raw = {
        "semantic_skills": [
            {
                "canonical": "AI-assisted coding",
                "search_equivalents": ["Copilot", "Cursor IDE", "AI pair programming"],
                "intent_strength": "preferred",
                "query_confidence": 0.86,
            },
            {
                "canonical": "курсорить",
                "search_equivalents": ["AI-assisted coding", "Copilot"],
                "intent_strength": "required",
                "query_confidence": 0.61,
            },
        ]
    }
    out = llm_client._normalize_llm_output(raw)
    assert any(x["canonical"] == "AI-assisted coding" for x in out["should_skills"])
    assert not any(x["canonical"] == "курсорить" for x in out["must_skills"])
    assert out["semantic_terms_promoted_to_should"] >= 1
