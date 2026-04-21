# Prescore Rerank Rollout

## Runtime config

- `PRESCORE_MODE=chat_legacy|rerank`
- `RERANK_ENDPOINT=http://10.118.133.147:8002/v1/rerank`
- `RERANK_MODEL=qwen3-vl-embedding-2b`
- `RERANK_API_KEY=`
- `RERANK_TIMEOUT_SECONDS=30`
- `RERANK_BATCH_SIZE=200`

По умолчанию используется `chat_legacy`, чтобы исключить внезапное изменение поведения.

## Safe rollout sequence

1. Развернуть версию с dual-mode и оставить `PRESCORE_MODE=chat_legacy`.
2. Проверить, что `/search/.../evaluate` и UI-прогресс работают как раньше.
3. На тестовом окружении включить `PRESCORE_MODE=rerank`.
4. Проверить метрики:
   - `prescore_mode`
   - `rerank_calls_total`
   - `rerank_batch_split_count`
   - `rerank_avg_score`
   - `parse_fail_count`
5. Сравнить latency и качество с `chat_legacy` на контрольной выборке 100-200 резюме.
6. Если есть деградация по качеству или стабильности, откатить только `PRESCORE_MODE` обратно в `chat_legacy`.

## Recovery policy in rerank mode

- приоритет 1: повтор вызова на уровне сети/endpoint;
- приоритет 2: автоматическое деление батча;
- приоритет 3: fallback-эвристика (если включена через `LLM_PRESCORE_ENABLE_FALLBACK`);
- приоритет 4: `unresolved` и статус `partial|error`.
