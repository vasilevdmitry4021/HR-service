# Тестирование HR Service

Краткая выжимка; полные команды и переменные окружения — в [README.md](../README.md) (раздел «Тестирование и CI»).

| Слой | Инструмент | Где лежит |
|------|------------|-----------|
| Backend unit + API | pytest, httpx TestClient, respx | `backend/tests/` |
| Frontend компоненты | Vitest, Testing Library | `frontend/**/*.test.ts(x)` |
| E2E | Playwright | `e2e/` |
| CI | GitHub Actions | `.github/workflows/test.yml`, `deploy.yml` |

Интеграционные тесты API помечены маркером `integration` и требуют PostgreSQL. Локально без БД: `pytest tests/ -m "not integration"`.
