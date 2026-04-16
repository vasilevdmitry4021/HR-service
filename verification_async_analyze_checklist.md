# Async Analyze Verification Checklist

## 1) Производительность и отсутствие очереди

- [ ] Запустить минимум 2 параллельные задачи `POST /search/{snapshot_id}/analyze/start` для разных пользователей/снимков.
- [ ] Во время выполнения analyze-job отправлять частые запросы:
  - [ ] `GET /api/v1/history`
  - [ ] `GET /api/v1/favorites`
  - [ ] `GET /api/v1/auth/me`
- [ ] Подтвердить, что latency фоновых read-эндпоинтов не деградирует кратно и не блокируется до завершения analyze.
- [ ] Проверить, что `GET /search/{snapshot_id}/analyze/progress` возвращает актуальные `processed_count/analyzed_count/status`.

## 2) Отказоустойчивость

- [ ] Смоделировать таймаут/ошибку LLM во время analyze-job.
- [ ] Убедиться, что progress переходит в `status=error`, `stage=error`, и выставляется `error`.
- [ ] Убедиться, что job не остается в `queued/running` бесконечно.
- [ ] Для ошибок HH (включая дневной лимит) проверить корректный текст ошибки в progress и на UI.

## 3) Корректность backend-контракта

- [ ] `POST /search/{snapshot_id}/analyze/start` возвращает `job_id`, `status`, `total_count`.
- [ ] `GET /search/{snapshot_id}/analyze/progress?job_id=...`:
  - [ ] 404 для несуществующего/протухшего `job_id`.
  - [ ] 403 для чужого `job_id`.
  - [ ] 400 для `job_id`, не относящегося к `snapshot_id`.
- [ ] После `status=done` проверить, что snapshot обновлен атомарно и содержит `llm_analysis` для top-N.

## 4) Регресс evaluate и точечного analyze

- [ ] Проверить flow `evaluate/start -> evaluate/progress` (interactive/background counters и partial scores).
- [ ] Проверить, что `POST /search/{snapshot_id}/analyze` (совместимый sync endpoint) по-прежнему работает.
- [ ] Проверить точечный `POST /candidates/{id}/analyze?q=...` после batch-операций.

## 5) Frontend UX и polling

- [ ] Кнопка "Детальный анализ (топ-15)" запускает `analyze/start`, а не sync analyze.
- [ ] UI показывает прогресс analyze (`status`, `processed/total`, `analyzed`).
- [ ] Конфликтующие batch-операции корректно блокируются, остальной экран остается интерактивным.
- [ ] После `status=done` список кандидатов автоматически обновляется.
