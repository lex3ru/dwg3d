# Планировка и учёт имущества здания

Система из двух подсистем над общим ядром: **планировка** — редактор здания (строится в 2D,
смотрится в 3D), расстановка мебели, оборудования, камер и светильников по слоям, расчёты
обзора камер и освещённости, проекты; **учёт имущества** — инвентарные единицы и остатки,
места хранения, движение документами, стоимость, инвентаризация по QR-меткам с телефона.

- [docs/TZ.md](docs/TZ.md) — техническое задание (принято заказчиком 16.10.2026).
- [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) — что сделано и что осталось по этапам.
- [docs/INSTALL.md](docs/INSTALL.md) — установка и обслуживание.

## Устройство

Модульный монолит (ТЗ 9): одно приложение и одна база.

| Каталог | Что |
|---|---|
| `server/` | сервер: Python 3.12, FastAPI, PostgreSQL; ядро `app/core`, модули `app/modules/*` |
| `web/` | интерфейс: React, TypeScript, Vite, Tailwind |
| `e2e/` | сценарии ТЗ в браузере (Playwright) |
| `deploy/` | установка: Docker Compose, Caddy (HTTPS), резервные копии |
| `docs/` | ТЗ, приёмка, установка, примеры данных (`docs/samples`) |
| `legacy/`, `legacy2/` | прежние версии — только справка, код не переносится (ТЗ 9.1) |

## Разработка

Нужны Docker, [uv](https://docs.astral.sh/uv/), Node.js 24.

```bash
# база для разработки и тестов
docker run -d --name planuchet-devdb -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=app -p 127.0.0.1:55432:5432 postgres:16-alpine

cd server && uv sync
uv run pytest                     # тесты сервера (создают свою базу app_test)
APP_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app APP_SECURE_COOKIES=false \
  uv run python -m app serve --port 8010     # сервер (с миграцией базы)
APP_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app \
  uv run python -m app create-admin          # первый администратор, печатает пароль

APP_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app \
  uv run python -m app sample polyclinic     # тестовое здание «Поликлиника» (ТЗ 7.2)

cd web && npm install && npm run dev          # интерфейс: http://localhost:5190
cd e2e && npm install && npx playwright test  # сценарии; E2E_URL, E2E_ADMIN, E2E_PASSWORD
```

В `.claude/launch.json` то же — конфигурации `server`, `worker`, `ui`.

Правила модулей (ТЗ 9.2) — в [server/app/modules/\_\_init\_\_.py](server/app/modules/__init__.py):
модуль держит таблицы в своей схеме базы, к модулям ниже обращается только через их `api`,
каждое изменение пишет в журнал в той же транзакции. Проверяет тест
`server/tests/test_architecture.py`.
