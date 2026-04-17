from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
import re
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_SPECIAL_CHARS_RE = re.compile(r'[:~!*]+')


@dataclass(frozen=True)
class HHQueryPlan:
    label: str
    text: str
    priority: int
    search_field: str | None = None
    relax_level: int = 0
    groups: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    parts: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _sanitize_token(value: str) -> str:
    text = str(value or "").strip().replace('"', "")
    text = _SPECIAL_CHARS_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _quote_token(value: str) -> str:
    token = _sanitize_token(value)
    if not token:
        return ""
    return f'"{token}"'


def _or_group(values: list[str]) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        quoted = _quote_token(value)
        if not quoted:
            continue
        key = quoted.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(quoted)
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    return f"({' OR '.join(terms)})"


def to_hh_text(groups: list[str]) -> str:
    """
    HH требует КАПС-операторы (AND/OR/NOT), иначе они трактуются как слова.
    """
    clean = [g.strip() for g in groups if g and g.strip()]
    return " AND ".join(clean)


def _split_by_length(group_pairs: list[tuple[str, str]], max_length: int) -> list[list[tuple[str, str]]]:
    if not group_pairs:
        return []
    chunks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for pair in group_pairs:
        candidate = current + [pair]
        text = to_hh_text([x[1] for x in candidate])
        if current and len(text) > max_length:
            chunks.append(current)
            current = [pair]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _trim_long_group(group_text: str, max_length: int) -> str:
    text = group_text.strip()
    if len(text) <= max_length:
        return text
    if " OR " not in text:
        return text[:max_length].strip()
    terms = [t.strip() for t in text.strip("()").split(" OR ") if t.strip()]
    if not terms:
        return text[:max_length].strip()
    kept = [terms[0]]
    for term in terms[1:]:
        candidate = f"({' OR '.join(kept + [term])})"
        if len(candidate) > max_length:
            break
        kept.append(term)
    candidate = f"({' OR '.join(kept)})"
    if len(candidate) > max_length:
        return candidate[:max_length].strip()
    return candidate


def _apply_length_guard(base: HHQueryPlan, max_length: int) -> list[HHQueryPlan]:
    text = base.text.strip()
    if not text:
        return []
    if len(text) <= max_length:
        return [base]

    guarded_groups: list[tuple[str, str]] = []
    for kind, group in base.groups:
        trimmed = _trim_long_group(group, max_length)
        guarded_groups.append((kind, trimmed))
    split_chunks = _split_by_length(guarded_groups, max_length)
    if not split_chunks:
        return []

    use_sf = bool(settings.hh_query_use_search_field)
    plans: list[HHQueryPlan] = []
    for idx, chunk in enumerate(split_chunks, start=1):
        chunk_text = to_hh_text([g for _, g in chunk])
        if len(chunk_text) > max_length:
            chunk_text = chunk_text[:max_length].strip()
        label = base.label if idx == 1 else f"{base.label}_split_{idx}"
        chunk_parts = _make_parts(chunk, use_search_field=use_sf)
        plans.append(
            replace(
                base,
                label=label,
                text=chunk_text,
                groups=tuple(chunk),
                parts=chunk_parts,
            )
        )
    logger.warning(
        "HH query split applied: label=%s chunks=%s max_length=%s",
        base.label,
        len(plans),
        max_length,
    )
    return plans


def _flatten_skill_terms(skill_obj: dict[str, Any], expanded_synonyms: dict[str, list[str]]) -> list[str]:
    canonical = str(skill_obj.get("canonical") or "").strip()
    raw_synonyms = skill_obj.get("synonyms")
    synonyms = [str(s).strip() for s in raw_synonyms] if isinstance(raw_synonyms, list) else []
    merged = [canonical, *synonyms, *(expanded_synonyms.get(canonical, []) or [])]
    out: list[str] = []
    seen: set[str] = set()
    for item in merged:
        key = _norm(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _hh_field_for_kind(kind: str, *, use_search_field: bool) -> str:
    if not use_search_field:
        return "everywhere"
    if kind == "role":
        return "position"
    if kind.startswith("must_") or kind.startswith("should"):
        return "skill"
    return "everywhere"


def _primary_groups(
    parsed: dict[str, Any],
    expanded_synonyms: dict[str, list[str]],
    *,
    use_search_field: bool = False,
) -> list[tuple[str, str]]:
    groups: list[tuple[str, str]] = []
    hard_skills_raw = parsed.get("hard_skills")
    risky_skills_raw = parsed.get("risky_skills")
    hard_skills = {
        _norm(str(x))
        for x in hard_skills_raw
        if isinstance(hard_skills_raw, list) and str(x).strip()
    }
    risky_skills = {
        _norm(str(x))
        for x in risky_skills_raw
        if isinstance(risky_skills_raw, list) and str(x).strip()
    }
    role_terms = parsed.get("must_position") or parsed.get("position_keywords") or []
    role_group = _or_group([str(x) for x in role_terms if str(x).strip()])
    if role_group:
        groups.append(("role", role_group))

    must_skills = parsed.get("must_skills")
    if not isinstance(must_skills, list):
        must_skills = []
    risky_terms: list[str] = []
    should_terms: list[str] = []
    for idx, skill_obj in enumerate(must_skills):
        if not isinstance(skill_obj, dict):
            continue
        canonical = str(skill_obj.get("canonical") or "").strip()
        if not canonical:
            continue
        canonical_norm = _norm(canonical)
        terms = _flatten_skill_terms(skill_obj, expanded_synonyms)
        intent = _norm(str(skill_obj.get("intent_strength") or "required")) or "required"
        conf_raw = skill_obj.get("query_confidence")
        query_conf = max(0.0, min(1.0, float(conf_raw))) if isinstance(conf_raw, (int, float)) else 0.7
        if canonical_norm in risky_skills:
            risky_terms.extend(terms)
            continue
        if intent != "required" or query_conf < 0.62:
            should_terms.extend(terms)
            continue
        if hard_skills and canonical_norm not in hard_skills:
            risky_terms.extend(terms)
            continue
        group = _or_group(terms)
        if group:
            groups.append((f"must_{idx}", group))

    should_skills = parsed.get("should_skills")
    if isinstance(should_skills, list):
        for item in should_skills:
            if isinstance(item, dict):
                canonical = str(item.get("canonical") or "").strip()
                terms = _flatten_skill_terms(item, expanded_synonyms)
                conf_raw = item.get("query_confidence")
                query_conf = (
                    max(0.0, min(1.0, float(conf_raw)))
                    if isinstance(conf_raw, (int, float))
                    else 0.55
                )
                intent = _norm(str(item.get("intent_strength") or "preferred")) or "preferred"
                if intent == "signal" or query_conf < 0.25:
                    risky_terms.extend(terms)
                elif canonical and _norm(canonical) in risky_skills:
                    risky_terms.extend(terms)
                else:
                    should_terms.extend(terms)
        risky_group = _or_group(risky_terms)
        if risky_group:
            groups.append(("should_risky", risky_group))
        should_group = _or_group(should_terms)
        if should_group:
            groups.append(("should", should_group))
    return groups


def _is_role_sensitive(parsed: dict[str, Any]) -> bool:
    role_terms = parsed.get("must_position") or parsed.get("position_keywords") or []
    if not isinstance(role_terms, list):
        return False
    return any(_norm(str(x)) for x in role_terms if str(x).strip())


def _make_parts(
    groups: list[tuple[str, str]],
    *,
    use_search_field: bool,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (_hh_field_for_kind(kind, use_search_field=use_search_field), text)
        for kind, text in groups
    )


def build_plans(parsed: dict[str, Any], expanded_synonyms: dict[str, list[str]]) -> list[HHQueryPlan]:
    max_length = max(200, int(settings.hh_query_max_text_length or 1500))
    use_sf = bool(settings.hh_query_use_search_field)
    plans: list[HHQueryPlan] = []
    groups = _primary_groups(parsed, expanded_synonyms, use_search_field=use_sf)
    if groups:
        primary = HHQueryPlan(
            label="primary",
            text=to_hh_text([g for _, g in groups]),
            priority=100,
            search_field="text" if use_sf else None,
            groups=tuple(groups),
            parts=_make_parts(groups, use_search_field=use_sf),
        )
        plans.extend(_apply_length_guard(primary, max_length))

        broad_groups = [g for g in groups if g[0] == "role"]
        must_groups = [g for g in groups if g[0].startswith("must_")]
        if must_groups and not _is_role_sensitive(parsed):
            broad_groups.append(must_groups[0])
        if broad_groups:
            broad = HHQueryPlan(
                label="broad",
                text=to_hh_text([g for _, g in broad_groups]),
                priority=70,
                search_field="text" if use_sf else None,
                groups=tuple(broad_groups),
                parts=_make_parts(broad_groups, use_search_field=use_sf),
            )
            plans.extend(_apply_length_guard(broad, max_length))

    soft_signals = parsed.get("soft_signals")
    if isinstance(soft_signals, list) and len(soft_signals) >= 2:
        bonus_group = _or_group([str(x) for x in soft_signals if str(x).strip()])
        if bonus_group:
            bonus_groups = [("bonus", bonus_group)]
            bonus = HHQueryPlan(
                label="bonus",
                text=bonus_group,
                priority=40,
                search_field="text" if use_sf else None,
                groups=(("bonus", bonus_group),),
                parts=_make_parts(bonus_groups, use_search_field=use_sf),
            )
            plans.extend(_apply_length_guard(bonus, max_length))

    return plans


def relax(plan: HHQueryPlan, level: int) -> HHQueryPlan:
    if level <= 0:
        return plan
    groups = list(plan.groups)
    for _ in range(level):
        risky_idx = next((i for i, (kind, _) in enumerate(groups) if kind == "should_risky"), None)
        if risky_idx is not None:
            groups.pop(risky_idx)
            continue
        should_idx = next((i for i, (kind, _) in enumerate(groups) if kind == "should"), None)
        if should_idx is not None:
            groups.pop(should_idx)
            continue
        must_idxs = [i for i, (kind, _) in enumerate(groups) if kind.startswith("must_")]
        if must_idxs:
            groups.pop(must_idxs[-1])
    relaxed_text = to_hh_text([g for _, g in groups])
    use_sf = bool(settings.hh_query_use_search_field)
    return replace(
        plan,
        text=relaxed_text,
        relax_level=max(0, int(level)),
        groups=tuple(groups),
        parts=_make_parts(groups, use_search_field=use_sf),
    )
