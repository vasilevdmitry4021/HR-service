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


def _join_terms(values: list[str], operator: str) -> str:
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
    return f"({f' {operator} '.join(terms)})"


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


def _collect_role_terms(parsed: dict[str, Any]) -> list[str]:
    role_terms = parsed.get("must_position") or parsed.get("position_keywords") or []
    if not isinstance(role_terms, list):
        return []
    return [str(x).strip() for x in role_terms if str(x).strip()]


def _collect_skill_terms(parsed: dict[str, Any], expanded_synonyms: dict[str, list[str]]) -> list[str]:
    collected: list[str] = []
    seen: set[str] = set()

    def add_term(value: str) -> None:
        normalized = _norm(value)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        collected.append(value.strip())

    semantic_groups: list[dict[str, Any]] = []
    for group_key in ("must_skills", "should_skills"):
        raw_groups = parsed.get(group_key)
        if isinstance(raw_groups, list):
            semantic_groups.extend(x for x in raw_groups if isinstance(x, dict))
    for item in semantic_groups:
        for term in _flatten_skill_terms(item, expanded_synonyms):
            add_term(term)

    if collected:
        return collected

    fallback = parsed.get("hard_skills")
    if not isinstance(fallback, list) or not fallback:
        fallback = parsed.get("skills")
    if isinstance(fallback, list):
        for item in fallback:
            if isinstance(item, str):
                add_term(item)
    return collected


def _hh_field_for_kind(kind: str, *, use_search_field: bool) -> str:
    if not use_search_field:
        return "everywhere"
    if kind == "role":
        return "position"
    if kind == "skills":
        return "skill"
    return "everywhere"


def _primary_groups(
    parsed: dict[str, Any],
    expanded_synonyms: dict[str, list[str]],
    *,
    search_mode: str,
) -> list[tuple[str, str]]:
    groups: list[tuple[str, str]] = []
    role_group = _or_group(_collect_role_terms(parsed))
    if role_group:
        groups.append(("role", role_group))
    skill_terms = _collect_skill_terms(parsed, expanded_synonyms)
    skill_operator = "AND" if search_mode == "precise" else "OR"
    skills_group = _join_terms(skill_terms, skill_operator)
    if skills_group:
        groups.append(("skills", skills_group))
    return groups


def _make_parts(
    groups: list[tuple[str, str]],
    *,
    use_search_field: bool,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (_hh_field_for_kind(kind, use_search_field=use_search_field), text)
        for kind, text in groups
    )


def build_plans(
    parsed: dict[str, Any],
    expanded_synonyms: dict[str, list[str]],
    *,
    search_mode: str = "precise",
) -> list[HHQueryPlan]:
    max_length = max(200, int(settings.hh_query_max_text_length or 1500))
    use_sf = bool(settings.hh_query_use_search_field)
    groups = _primary_groups(
        parsed,
        expanded_synonyms,
        search_mode="mass" if search_mode == "mass" else "precise",
    )
    if not groups:
        return []
    primary = HHQueryPlan(
        label="primary",
        text=to_hh_text([g for _, g in groups]),
        priority=100,
        search_field="text" if use_sf else None,
        groups=tuple(groups),
        parts=_make_parts(groups, use_search_field=use_sf),
    )
    return _apply_length_guard(primary, max_length)


def relax(plan: HHQueryPlan, level: int) -> HHQueryPlan:
    if level <= 0:
        return plan
    groups = list(plan.groups)
    # В новом режиме `precise/mass` не используем отдельные ветки relax,
    # но сохраняем совместимость вызова: при relax убираем группу skills.
    if level > 0:
        groups = [pair for pair in groups if pair[0] != "skills"]
    relaxed_text = to_hh_text([g for _, g in groups])
    use_sf = bool(settings.hh_query_use_search_field)
    return replace(
        plan,
        text=relaxed_text,
        relax_level=max(0, int(level)),
        groups=tuple(groups),
        parts=_make_parts(groups, use_search_field=use_sf),
    )
