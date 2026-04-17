from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.skill_synonym import SkillSynonym
from app.services import llm_client
from app.services.skill_expansion_stopwords import GENERIC_SKILL_STOPWORDS

logger = logging.getLogger(__name__)

_ONLY_WORD_CHARS_RE = re.compile(r"^[\w\s+\-./#&()]+$", re.UNICODE)
_HAS_LETTER_RE = re.compile(r"[a-zA-Zа-яА-Я]")
_RISKY_SKILL_PATTERNS = (
    re.compile(r"\b(вайб|vibe)\w*\b", re.IGNORECASE),
    re.compile(r"\b(ai\s*pair|pair\s*programming)\b", re.IGNORECASE),
    re.compile(r"\b(copilot|cursor\s*ide|курсор\w*)\b", re.IGNORECASE),
    re.compile(r"\b(rockstar|ninja|guru|evangelist)\b", re.IGNORECASE),
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _is_sane_synonym(raw_synonym: str, canonical_norm: str) -> bool:
    syn_norm = _norm(raw_synonym)
    if not syn_norm or syn_norm == canonical_norm:
        return False
    if len(syn_norm) < 2 or len(syn_norm) > 64:
        return False
    if not _HAS_LETTER_RE.search(syn_norm):
        return False
    if syn_norm in GENERIC_SKILL_STOPWORDS:
        return False
    if not _ONLY_WORD_CHARS_RE.match(syn_norm):
        return False
    return True


def _sanitize_synonyms(
    canonical: str,
    synonyms: Iterable[str],
    *,
    max_per_canonical: int,
) -> list[str]:
    canonical_clean = str(canonical or "").strip()
    canonical_norm = _norm(canonical_clean)
    seen: set[str] = set()
    out: list[str] = []
    for raw in synonyms:
        text = str(raw or "").strip()
        if not text:
            continue
        key = _norm(text)
        if key in seen:
            continue
        seen.add(key)
        if not _is_sane_synonym(text, canonical_norm):
            continue
        out.append(text)
        if len(out) >= max_per_canonical:
            break
    return out


def skill_hard_confidence(
    canonical: str,
    synonyms: Iterable[str],
    *,
    manual_source: bool = False,
) -> float:
    canonical_clean = str(canonical or "").strip()
    canonical_norm = _norm(canonical_clean)
    clean_synonyms = _sanitize_synonyms(
        canonical_clean,
        synonyms,
        max_per_canonical=max(1, int(settings.skill_synonyms_per_canonical_max or 8)),
    )
    score = 0.48
    if not canonical_norm:
        return 0.0
    if not _HAS_LETTER_RE.search(canonical_clean):
        return 0.0
    if any(rx.search(canonical_norm) for rx in _RISKY_SKILL_PATTERNS):
        score -= 0.45
    if len(canonical_clean) < 2 or len(canonical_clean) > 64:
        score -= 0.2
    if clean_synonyms:
        score += 0.12 if len(clean_synonyms) >= 2 else 0.07
    else:
        score -= 0.15
    if manual_source:
        score += 0.28
    return max(0.0, min(1.0, score))


def _normalize_intent(value: Any, *, fallback: str) -> str:
    raw = _norm(str(value or ""))
    mapping = {
        "required": "required",
        "must": "required",
        "hard": "required",
        "preferred": "preferred",
        "should": "preferred",
        "optional": "preferred",
        "signal": "signal",
        "soft": "signal",
    }
    return mapping.get(raw, fallback)


def _normalize_query_confidence(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    conf = float(value)
    if conf > 1.0:
        conf = conf / 100.0
    return max(0.0, min(1.0, conf))


def _sanitize_equivalents(canonical: str, values: Iterable[str]) -> list[str]:
    return _sanitize_synonyms(
        canonical,
        values,
        max_per_canonical=max(1, int(settings.skill_synonyms_per_canonical_max or 8)),
    )


def classify_parsed_skills(
    parsed: dict[str, Any],
    expanded_synonyms: dict[str, list[str]],
    *,
    expansion_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    must_skills = parsed.get("must_skills")
    if not isinstance(must_skills, list):
        must_skills = []
    should_skills = parsed.get("should_skills")
    if not isinstance(should_skills, list):
        should_skills = []
    soft_signals = parsed.get("soft_signals")
    if not isinstance(soft_signals, list):
        soft_signals = []

    hardness_stats = (
        (expansion_stats or {}).get("skill_hardness")
        if isinstance(expansion_stats, dict)
        else None
    )
    hardness_stats = hardness_stats if isinstance(hardness_stats, dict) else {}

    final_must: list[dict[str, Any]] = []
    final_should: list[dict[str, Any]] = []
    hard_skills: list[str] = []
    risky_skills: list[str] = []
    risk_profile: list[dict[str, Any]] = []
    demote_to_soft: list[str] = []
    promoted_to_must = 0
    promoted_to_should = 0
    semantic_jargon_terms_total = 0

    def _classify_bucket(
        item: dict[str, Any],
        *,
        fallback_intent: str,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        canonical = str(item.get("canonical") or "").strip()
        own_synonyms = _as_string_list(item.get("synonyms"))
        own_equivalents = _as_string_list(item.get("search_equivalents"))
        merged_equivalents = _sanitize_equivalents(
            canonical,
            [*own_synonyms, *own_equivalents, *(expanded_synonyms.get(canonical, []) or [])],
        )
        stat_row = hardness_stats.get(_norm(canonical)) or hardness_stats.get(canonical) or {}
        manual_boost = bool(stat_row.get("manual_source"))
        hard_confidence = float(
            stat_row.get("hard_confidence")
            if isinstance(stat_row, dict) and stat_row.get("hard_confidence") is not None
            else skill_hard_confidence(canonical, merged_equivalents, manual_source=manual_boost)
        )
        query_confidence = _normalize_query_confidence(item.get("query_confidence"))
        if query_confidence is None:
            query_confidence = hard_confidence
        intent = _normalize_intent(item.get("intent_strength"), fallback=fallback_intent)
        eq_quality = min(1.0, len(merged_equivalents) / 3.0)
        semantic_confidence = max(
            0.0,
            min(1.0, 0.55 * query_confidence + 0.3 * hard_confidence + 0.15 * eq_quality),
        )
        is_risky = any(rx.search(_norm(canonical)) for rx in _RISKY_SKILL_PATTERNS)
        if intent == "signal" or semantic_confidence < 0.28:
            bucket = "soft"
        elif intent == "required" and semantic_confidence >= 0.64 and eq_quality >= 0.2 and not (
            is_risky and semantic_confidence < 0.82
        ):
            bucket = "must"
        else:
            bucket = "should"
        skill_obj = {
            "canonical": canonical,
            "synonyms": own_synonyms,
            "search_equivalents": merged_equivalents,
            "intent_strength": intent,
            "query_confidence": round(query_confidence, 3),
        }
        profile_row = {
            "canonical": canonical,
            "hard_confidence": round(hard_confidence, 3),
            "query_confidence": round(query_confidence, 3),
            "semantic_confidence": round(semantic_confidence, 3),
            "intent_strength": intent,
            "equivalents_count": len(merged_equivalents),
            "risk": "risky" if is_risky or semantic_confidence < 0.55 else "hard",
            "bucket": bucket,
            "source": "expansion",
            "manual_source": manual_boost,
        }
        return bucket, skill_obj, profile_row

    incoming: list[tuple[str, dict[str, Any]]] = []
    for item in must_skills:
        if isinstance(item, dict):
            incoming.append(("required", item))
    for item in should_skills:
        if isinstance(item, dict):
            incoming.append(("preferred", item))

    seen_keys: set[str] = set()
    soft_set = {_norm(x) for x in soft_signals if str(x).strip()}
    for fallback_intent, item in incoming:
        canonical = str(item.get("canonical") or "").strip()
        if not canonical:
            continue
        canonical_key = _norm(canonical)
        if canonical_key in seen_keys:
            continue
        seen_keys.add(canonical_key)
        bucket, skill_obj, profile_row = _classify_bucket(item, fallback_intent=fallback_intent)
        risk_profile.append(profile_row)
        if profile_row["risk"] == "risky":
            risky_skills.append(canonical)
        if profile_row["risk"] == "hard":
            hard_skills.append(canonical)
        if any(rx.search(_norm(canonical)) for rx in _RISKY_SKILL_PATTERNS):
            semantic_jargon_terms_total += 1
        if bucket == "must":
            final_must.append(skill_obj)
            promoted_to_must += 1
        elif bucket == "should":
            final_should.append(skill_obj)
            promoted_to_should += 1
        else:
            if canonical_key not in soft_set:
                soft_signals.append(canonical)
                soft_set.add(canonical_key)
                demote_to_soft.append(canonical)
    return {
        "must_skills": final_must,
        "should_skills": final_should,
        "soft_signals": soft_signals,
        "hard_skills": list(dict.fromkeys(hard_skills)),
        "risky_skills": list(dict.fromkeys(risky_skills)),
        "risky_demoted_to_should": promoted_to_should,
        "risky_demoted_to_soft": len(demote_to_soft),
        "semantic_jargon_terms_total": semantic_jargon_terms_total,
        "semantic_terms_promoted_to_should": promoted_to_should,
        "semantic_terms_promoted_to_must": promoted_to_must,
        "semantic_terms_demoted_to_soft": len(demote_to_soft),
        "skill_risk_profile": risk_profile,
    }


def _extract_llm_expansion(raw: dict[str, Any]) -> dict[str, list[str]]:
    """
    Поддерживает несколько форматов:
    - {"skills": [{"canonical": "...", "synonyms": [...]}, ...]}
    - {"items": [{"canonical": "...", "synonyms": [...]}, ...]}
    - {"python": ["py", ...], ...}
    """
    out: dict[str, list[str]] = {}

    for top_key in ("skills", "items", "results"):
        items = raw.get(top_key)
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                canonical = str(item.get("canonical") or "").strip()
                if not canonical:
                    continue
                synonyms = _as_string_list(item.get("synonyms"))
                out[canonical] = synonyms

    if out:
        return out

    for key, val in raw.items():
        if isinstance(val, list):
            canonical = str(key or "").strip()
            if not canonical:
                continue
            out[canonical] = _as_string_list(val)
    return out


def _fetch_llm_synonyms_batch(canonicals: list[str], db: Session | None) -> dict[str, list[str]]:
    if not canonicals:
        return {}
    if not llm_client.llm_connection_configured(db):
        return {}

    payload = ", ".join(f'"{c}"' for c in canonicals)
    prompt = (
        "Верни JSON-объект с ключом skills: массив объектов вида "
        '{"canonical":"...", "synonyms":["..."]}. '
        "Для каждого canonical предложи 5-8 эквивалентных формулировок навыка, "
        "включая русские и английские варианты, названия инструментов и частые написания. "
        "Не добавляй общие слова и смежные, но неравнозначные технологии. "
        f"Навыки: [{payload}]"
    )
    raw = llm_client.call_llm_for_json_object(db, prompt, timeout=120.0)
    if not isinstance(raw, dict):
        return {}
    return _extract_llm_expansion(raw)


def expand_skills(
    canonicals: list[str],
    db: Session | None,
) -> dict[str, list[str]]:
    """
    Возвращает {canonical -> synonyms} c TTL-кэшем в БД и батч-расширением через LLM.
    """
    results, _stats = expand_skills_with_stats(canonicals, db)
    return results


def expand_skills_with_stats(
    canonicals: list[str],
    db: Session | None,
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """
    Расширяет навыки и возвращает (results, stats).
    stats: cache_hit, cache_miss, expired, llm_call_count.
    """
    max_per = max(1, int(settings.skill_synonyms_per_canonical_max or 8))
    ttl_days = max(1, int(settings.skill_synonyms_ttl_days or 30))
    now = datetime.now(timezone.utc)

    stats: dict[str, Any] = {
        "cache_hit": 0,
        "cache_miss": 0,
        "expired": 0,
        "llm_call_count": 0,
        "skill_hardness": {},
    }

    by_norm: dict[str, str] = {}
    for skill in canonicals:
        text = str(skill or "").strip()
        if not text:
            continue
        key = _norm(text)
        if key and key not in by_norm:
            by_norm[key] = text
    if not by_norm:
        return {}, stats

    results: dict[str, list[str]] = {c: [] for c in by_norm.values()}
    missing_norms: list[str] = list(by_norm.keys())

    if db is not None:
        rows = db.scalars(
            select(SkillSynonym).where(SkillSynonym.canonical_norm.in_(missing_norms))
        ).all()
        fresh_norms: set[str] = set()
        for row in rows:
            canonical_norm = _norm(row.canonical_norm)
            canonical = by_norm.get(canonical_norm) or row.canonical
            raw_synonyms = _as_string_list(row.synonyms_json)
            clean = _sanitize_synonyms(
                canonical,
                raw_synonyms,
                max_per_canonical=max_per,
            )
            manual_row = row.source == "manual"
            non_expired = row.expires_at is None or row.expires_at >= now
            if manual_row or non_expired:
                results[canonical] = clean
                fresh_norms.add(canonical_norm)
                stats["cache_hit"] += 1
                stats["skill_hardness"][canonical_norm] = {
                    "hard_confidence": round(
                        skill_hard_confidence(canonical, clean, manual_source=manual_row),
                        3,
                    ),
                    "manual_source": manual_row,
                    "synonyms_count": len(clean),
                }
            else:
                stats["expired"] += 1
        missing_norms = [k for k in missing_norms if k not in fresh_norms]

    stats["cache_miss"] = len(missing_norms)

    if missing_norms:
        query_canonicals = [by_norm[k] for k in missing_norms]
        llm_map = _fetch_llm_synonyms_batch(query_canonicals, db)
        if llm_map:
            stats["llm_call_count"] += 1
        for canonical_norm in missing_norms:
            canonical = by_norm[canonical_norm]
            raw_synonyms = llm_map.get(canonical, [])
            clean = _sanitize_synonyms(
                canonical,
                raw_synonyms,
                max_per_canonical=max_per,
            )
            results[canonical] = clean
            stats["skill_hardness"][canonical_norm] = {
                "hard_confidence": round(
                    skill_hard_confidence(canonical, clean, manual_source=False),
                    3,
                ),
                "manual_source": False,
                "synonyms_count": len(clean),
            }
            if db is None:
                continue
            existing = db.scalars(
                select(SkillSynonym).where(SkillSynonym.canonical_norm == canonical_norm)
            ).first()
            if existing is not None and existing.source == "manual":
                continue
            expires_at = now + timedelta(days=ttl_days)
            if existing is None:
                db.add(
                    SkillSynonym(
                        canonical_norm=canonical_norm,
                        canonical=canonical,
                        synonyms_json=clean,
                        source="llm",
                        expires_at=expires_at,
                    )
                )
            else:
                existing.canonical = canonical
                existing.synonyms_json = clean
                existing.source = "llm"
                existing.expires_at = expires_at
        if db is not None:
            db.flush()

    return results, stats
