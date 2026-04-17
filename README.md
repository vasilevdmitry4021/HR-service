# HR Service

Стек: FastAPI + PostgreSQL + Next.js 14 (App Router).

## Быстрый старт (Docker)

1. Скопируйте `backend/.env.example` в `backend/.env` и при необходимости поправьте значения.
2. Скопируйте `.env.example` в `.env` (для Docker Compose).
3. Скопируйте `frontend/.env.example` в `frontend/.env.local` при необходимости.
4. Из корня проекта:

```bash
docker compose up --build
```

При старте контейнера `backend` автоматически выполняется `alembic upgrade head`, затем поднимается API.

При необходимости миграции можно выполнить вручную:

```bash
docker compose exec backend alembic upgrade head
```

- API: <http://localhost:8000> (`GET /health`, REST под префиксом `/api/v1`)
- Веб: <http://localhost:3000> (поиск: `/search`, история: `/history`, избранное: `/favorites`, карточка кандидата: `/candidates/[id]`, вход: `/login`, HeadHunter: `/settings`)

Экспорт PDF резюме: в `backend/.env` включите `FEATURE_PDF_EXPORT=true`, в `frontend/.env.local` — `NEXT_PUBLIC_FEATURE_PDF_EXPORT=true`, затем на карточке кандидата появится кнопка «Скачать PDF» (`GET /api/v1/candidates/{id}/pdf`).

## Локальная разработка без Docker

**Backend:** из каталога `backend` создайте виртуальное окружение, установите зависимости из `requirements.txt`, задайте `DATABASE_URL`, выполните `alembic upgrade head`, затем запустите `uvicorn app.main:app --reload`.

**Frontend:** из каталога `frontend` выполните `npm install` и `npm run dev`.

### Безопасный bootstrap супер-админов (пустая БД)

При открытой регистрации супер-права нельзя назначать через email в конфиге. Используйте только флаг `users.is_super_admin` в БД через CLI:

```bash
cd backend
python -m app.cli.admin_bootstrap create-super-admin --email admin@example.com --password "StrongPass123!"
```

Команды:

- `python -m app.cli.admin_bootstrap create-super-admin --email ... --password ...` — создать пользователя (если его нет) и выдать super-admin.
- `python -m app.cli.admin_bootstrap grant-super-admin --email ...` — выдать super-admin существующему пользователю.
- `python -m app.cli.admin_bootstrap revoke-super-admin --email ...` — снять super-admin (с защитой от снятия последнего супер-админа).

Безопасный порядок деплоя:

1. Применить миграции: `alembic upgrade head`.
2. Выполнить `create-super-admin` для первого привилегированного пользователя.
3. Войти этим пользователем и проверить `GET /api/v1/auth/me` (`is_super_admin=true`).
4. Только после этого открывать внешнюю регистрацию/доступ.

---

## Тестирование и CI

### Backend (pytest)

Из каталога `backend`:

```bash
pip install -r requirements-dev.txt
```

- **Только unit-тесты** (без PostgreSQL): `pytest tests/ -m "not integration"`
- **Полный набор** (включая REST-интеграцию): нужна БД PostgreSQL и миграции. По умолчанию используется `TEST_DATABASE_URL` или `postgresql://hr:hr@127.0.0.1:5432/hr_service_test`. Создайте базу и выполните `alembic upgrade head`, затем:

```bash
pytest tests/ -v
```

Структура: `tests/test_nlp_service.py`, `tests/test_relevance_service.py`, `tests/test_hh_client.py` (моки HTTP через [respx](https://lundberg.github.io/respx/)), `tests/test_api/` — сценарии API.

### Frontend (Vitest)

Из каталога `frontend`:

```bash
npm install
npm run test
```

Тесты: компоненты поиска (`SearchInput`, `CandidateCard`, `FilterPanel`), стор авторизации, утилиты `search-filters`.

### E2E (Playwright)

#### Учётные данные для входа в систему

**Готового логина и пароля в проекте нет** — пользователей создаёт только регистрация (`POST /api/v1/auth/register` или страница `/register`). Минимальная длина пароля: **8 символов** (см. API).

Как войти вручную:

1. Откройте <http://localhost:3000/register> (или `/login`, если пользователь уже есть).
2. Укажите **любой валидный email** и пароль **не короче 8 символов**.
3. После регистрации вы попадёте на `/search`; тот же email и пароль подойдут для `/login`.

Автотесты E2E каждый раз создают **нового** пользователя (случайный email вида `e2e_…@example.com`, пароль в сценарии — `e2e-pass-12`), отдельно заводить пользователя под тесты не нужно.

#### Как запустить E2E самостоятельно

**Предусловие:** отвечают API (<http://localhost:8000/health>) и фронт (<http://localhost:3000>). Удобнее всего поднять стек через Docker (см. «Быстрый старт»); миграции применяются при старте `backend`. При сбое схемы: `docker compose exec backend alembic upgrade head`.

**1. Один раз в корне репозитория** установите зависимости и браузер для Playwright:

```bash
npm install
npx playwright install chromium
```

**2. Задайте URL** (если приложение не на `127.0.0.1` или другие порты — подставьте свои):

- **Linux / macOS (bash):**

```bash
export PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000
export PLAYWRIGHT_API_URL=http://127.0.0.1:8000
npm run test:e2e
```

- **Windows (PowerShell):**

```powershell
$env:PLAYWRIGHT_BASE_URL="http://127.0.0.1:3000"
$env:PLAYWRIGHT_API_URL="http://127.0.0.1:8000"
npm run test:e2e
```

**3. Полезные команды Playwright**

- отладка с UI: `npx playwright test --ui`
- только Chromium: уже так настроено в `playwright.config.ts`
- отчёт после прогона: `npx playwright show-report`

**4. Если в браузере теста открывается 404 на `/register` или `/login`**

У frontend в Docker отдельный volume для `.next`; иногда кэш не совпадает с текущим кодом. Сбросьте контейнер frontend с удалением анонимного volume и поднимите снова:

```bash
docker compose stop frontend
docker compose rm -sfv frontend
docker compose up -d frontend
```

Флаг `-v` у `compose rm` сбрасывает анонимные volumes сервиса (в т.ч. устаревший `.next`).

Подождите 30–60 секунд, пока `next dev` соберёт страницы, проверьте в браузере <http://localhost:3000/register>, затем снова `npm run test:e2e`.

**Вариант без Docker:** поднимите PostgreSQL, backend (`uvicorn`) и frontend (`npm run dev` или `npm run build` + `npm run start`) с `NEXT_PUBLIC_API_URL`, указывающим на API; дальше шаги 1–3 те же.

Сценарии лежат в каталоге [`e2e/`](e2e/) (регистрация → поиск → избранное; вход существующего пользователя).

### GitHub Actions

- [`.github/workflows/test.yml`](.github/workflows/test.yml) — три job: backend (pytest + PostgreSQL service), frontend (`npm run lint` и `npm run test`), E2E (поднимает API и Next.js, затем Playwright).
- [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) — ручной запуск (`workflow_dispatch`), заготовка под ваш деплой.

---

## Документация по домену

Требования и спецификации: каталог [`Documents/`](Documents/) (`Требования.md`, `Техническая спецификация.md`, `User Stories.md`, `Roadmap.md` и др.).
