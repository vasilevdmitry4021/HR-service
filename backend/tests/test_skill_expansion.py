from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.skill_synonym import SkillSynonym
from app.services import skill_expansion


def test_expand_skills_cache_hit_uses_db_without_llm(db_session, monkeypatch) -> None:
    db_session.add(
        SkillSynonym(
            canonical_norm="python",
            canonical="Python",
            synonyms_json=["Py", "Питон"],
            source="llm",
            expires_at=datetime.now(timezone.utc) + timedelta(days=2),
        )
    )
    db_session.commit()
    monkeypatch.setattr(skill_expansion.llm_client, "llm_connection_configured", lambda _db: True)
    monkeypatch.setattr(skill_expansion.llm_client, "call_llm_for_json_object", lambda *_args, **_kwargs: {"skills": []})
    out = skill_expansion.expand_skills(["Python"], db_session)
    assert out["Python"] == ["Py", "Питон"]


def test_expand_skills_ttl_expired_calls_llm_and_updates(db_session, monkeypatch) -> None:
    db_session.add(
        SkillSynonym(
            canonical_norm="kafka",
            canonical="Kafka",
            synonyms_json=["очереди"],
            source="llm",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db_session.commit()
    monkeypatch.setattr(skill_expansion.llm_client, "llm_connection_configured", lambda _db: True)
    monkeypatch.setattr(
        skill_expansion.llm_client,
        "call_llm_for_json_object",
        lambda *_args, **_kwargs: {
            "skills": [{"canonical": "Kafka", "synonyms": ["Apache Kafka", "Streaming platform"]}]
        },
    )
    out = skill_expansion.expand_skills(["Kafka"], db_session)
    assert "Apache Kafka" in out["Kafka"]
    row = db_session.query(SkillSynonym).filter(SkillSynonym.canonical_norm == "kafka").one()
    assert "Apache Kafka" in (row.synonyms_json or [])


def test_expand_skills_manual_overrides_llm(db_session, monkeypatch) -> None:
    db_session.add(
        SkillSynonym(
            canonical_norm="react",
            canonical="React",
            synonyms_json=["ReactJS"],
            source="manual",
            expires_at=None,
        )
    )
    db_session.commit()
    monkeypatch.setattr(skill_expansion.llm_client, "llm_connection_configured", lambda _db: True)
    monkeypatch.setattr(
        skill_expansion.llm_client,
        "call_llm_for_json_object",
        lambda *_args, **_kwargs: {"skills": [{"canonical": "React", "synonyms": ["Frontend", "web"]}]},
    )
    out = skill_expansion.expand_skills(["React"], db_session)
    assert out["React"] == ["ReactJS"]


def test_sanity_filter_removes_noise(monkeypatch) -> None:
    monkeypatch.setattr(skill_expansion.settings, "skill_synonyms_per_canonical_max", 4)
    clean = skill_expansion._sanitize_synonyms(
        "Python",
        ["python", "ai", "Py", "  ", "123", "p", "CPython", "web", "Py"],
        max_per_canonical=4,
    )
    assert clean == ["Py", "CPython"]


def test_skill_hard_confidence_manual_source_boosts_score() -> None:
    base = skill_expansion.skill_hard_confidence("Kafka", ["Apache Kafka"], manual_source=False)
    boosted = skill_expansion.skill_hard_confidence("Kafka", ["Apache Kafka"], manual_source=True)
    assert boosted > base


def test_classify_parsed_skills_demotes_risky_must() -> None:
    parsed = {
        "must_skills": [
            {"canonical": "Python", "synonyms": [], "intent_strength": "required", "query_confidence": 0.9},
            {
                "canonical": "вайбкодинг",
                "synonyms": ["vibe coding"],
                "intent_strength": "required",
                "query_confidence": 0.45,
            },
        ],
        "should_skills": [],
        "soft_signals": [],
    }
    out = skill_expansion.classify_parsed_skills(parsed, {"Python": ["Py"]}, expansion_stats={})
    assert [x["canonical"] for x in out["must_skills"]] == ["Python"]
    assert not any(x["canonical"] == "вайбкодинг" for x in out["must_skills"])
    assert "вайбкодинг" in out["risky_skills"]
    assert (
        any(x["canonical"] == "вайбкодинг" for x in out["should_skills"])
        or "вайбкодинг" in out["soft_signals"]
    )
    assert out["semantic_terms_promoted_to_must"] >= 1
    assert out["semantic_jargon_terms_total"] >= 1
