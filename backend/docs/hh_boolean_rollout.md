# Rollout HH Boolean Query (staging)

## 1) Включение флага

На staging установить:

- `FEATURE_HH_BOOLEAN_QUERY=true`
- `SEARCH_RECALL_TARGET_MIN=60`
- `SEARCH_RECALL_TARGET_MAX=300`
- `SEARCH_MAX_RECALL=300`
- `SEARCH_BONUS_SHARE_MAX=0.2`
- `SEARCH_BONUS_GUARD_TOP_N=30` — число позиций в финальном топе, внутри которого ограничивается доля bonus-кандидатов
- `HH_QUERY_USE_SEARCH_FIELD=true` — раскладывать роль в `text.position`, навыки в `text.skill`

## 2) Набор кейсов для прогонки

Минимальный список запросов:

1. `системный аналитик, микросервисы, web/mobile, вайбкодинг`
2. `аналитик + микросервисы + bpmn + ai pair`
3. `backend python, kafka, event-driven, cloud`
4. `product analyst, sql, ab testing, startup mvp`
5. `qa automation, k8s, ai pair programming`

## 3) Сбор метрик

Логгер `search.metrics` пишет JSON на каждый `/search`.
Нужно собрать JSONL для двух режимов:

- baseline: `feature_hh_boolean_query=false`
- experiment: `feature_hh_boolean_query=true`

## 4) Сравнение до/после

Пример:

```bash
python backend/scripts/search_metrics_dashboard.py --input search-metrics.jsonl
```

Смотрим:

- `avg_recall_pool_size` (должен расти)
- `avg_latency_ms` (не должен деградировать критично)
- `relax_case_share` (контроль «узких» запросов)
- доли `primary/broad/bonus` в топе
- `avg_parse_latency_ms` — время NLP-парсинга
- `avg_expand_latency_ms` — время расширения синонимов
- `avg_skill_cache_hit_rate` — доля кэш-попаданий при расширении навыков
- `skill_expansion_cache` — в каждом запросе: `cache_hit`, `cache_miss`, `expired`, `llm_call_count`

## 5) Критерии приёмки

- precision@10 не ниже baseline
- recall@300 выше baseline на проблемных кейсах
- бонусные кандидаты не доминируют в топе (контроль через `SEARCH_BONUS_SHARE_MAX`)

## 6) Обработка жаргона и низкочастотных терминов

### Правила демоции

- Термины с низкой `hard_confidence` не попадают в `must`-группы HH-запроса.
- Рискованные термины демотируются в `should_risky` (ослабляются первыми при `relax`).
- Самые шумные термины (очень низкая уверенность) переносятся в `soft_signals`/`bonus`-контур.

### Признаки риска

- Жаргонные/маркетинговые формулировки (`вайбкодинг`, `vibe coding`, `AI pair`, `copilot`).
- Слабая или пустая эквивалентность после санитизации синонимов.
- Нестабильная форма термина (шум, слишком короткий/невалидный токен).
- Отсутствие ручного усиления (`source="manual"` в `skill_synonyms`).

### Проверка на staging

- Прогнать пары запросов: `hard-only` и `hard + jargon` с одинаковыми фильтрами.
- Сравнить `recall_pool_size` и `found` между парами: деградация при добавлении жаргона недопустима.
- Проверить `search.metrics` поля:
  - `risky_terms_total`,
  - `risky_terms_demoted_to_should`,
  - `risky_terms_demoted_to_soft`,
  - `hard_terms_used_in_primary`.
- Дополнительно проверить `hh_queries[*].risky_groups` и `hh_queries[*].relax_step`, чтобы видеть эффект демоции в фактических запросах.

### Критерий приёмки для жаргонных кейсов

- Жаргонные/низкочастотные термины не становятся обязательными HH-фильтрами по умолчанию.
- Для запросов с жаргоном `recall_pool_size` и `found` не падают кратно относительно `hard-only` варианта.
- Поведение воспроизводимо: демоция и итог по recall фиксируются в метриках и тестах.
