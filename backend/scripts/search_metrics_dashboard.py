from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _load_json_lines(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _avg(values: list[float]) -> float:
    return round(mean(values), 3) if values else 0.0


def _build_report(rows: list[dict[str, Any]], enabled: bool) -> dict[str, Any]:
    subset = [r for r in rows if bool(r.get("feature_hh_boolean_query")) is enabled]
    if not subset:
        return {"count": 0}
    recall_pool = [float(r.get("recall_pool_size") or 0) for r in subset]
    latency_ms = [float((r.get("latency_ms") or {}).get("total") or 0) for r in subset]
    relax_share = sum(1 for r in subset if r.get("relax_used")) / len(subset)
    primary = [float((r.get("top_match_sources") or {}).get("primary") or 0) for r in subset]
    broad = [float((r.get("top_match_sources") or {}).get("broad") or 0) for r in subset]
    bonus = [float((r.get("top_match_sources") or {}).get("bonus") or 0) for r in subset]

    parse_latency = [float((r.get("latency_ms") or {}).get("parse") or 0) for r in subset]
    expand_latency = [float((r.get("latency_ms") or {}).get("expand") or 0) for r in subset if (r.get("latency_ms") or {}).get("expand") is not None]

    cache_stats = [r.get("skill_expansion_cache") or {} for r in subset]
    cache_hits = [float(c.get("cache_hit") or 0) for c in cache_stats if c]
    cache_misses = [float(c.get("cache_miss") or 0) for c in cache_stats if c]
    cache_hit_rates: list[float] = []
    for c in cache_stats:
        if not c:
            continue
        total = float(c.get("cache_hit") or 0) + float(c.get("cache_miss") or 0)
        if total > 0:
            cache_hit_rates.append(float(c.get("cache_hit") or 0) / total)

    report: dict[str, Any] = {
        "count": len(subset),
        "avg_recall_pool_size": _avg(recall_pool),
        "avg_latency_ms": _avg(latency_ms),
        "relax_case_share": round(relax_share, 4),
        "avg_primary_in_top": _avg(primary),
        "avg_broad_in_top": _avg(broad),
        "avg_bonus_in_top": _avg(bonus),
        "avg_parse_latency_ms": _avg(parse_latency),
    }
    if expand_latency:
        report["avg_expand_latency_ms"] = _avg(expand_latency)
    if cache_hit_rates:
        report["avg_skill_cache_hit_rate"] = _avg(cache_hit_rates)
    if cache_hits:
        report["avg_skill_cache_hits"] = _avg(cache_hits)
    if cache_misses:
        report["avg_skill_cache_misses"] = _avg(cache_misses)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сводка метрик /search до и после feature_hh_boolean_query"
    )
    parser.add_argument("--input", required=True, help="Путь к JSONL-логу search.metrics")
    args = parser.parse_args()

    rows = _load_json_lines(Path(args.input))
    report = {
        "baseline_off": _build_report(rows, enabled=False),
        "boolean_on": _build_report(rows, enabled=True),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
