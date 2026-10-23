# AGENTS.md — Планировка и учёт имущества здания (planuchet)

> Карта проекта для людей и ИИ-агентов (Claude Code, Codex и любых других).
> Держите файл короче 150 строк: подробности — в `docs/` и навыках.
> Правки — только через MR. Пишите руками: сгенерированные инструкции работают хуже.

## Что это

Одно приложение и одна база (модульный монолит) с двумя подсистемами над общим ядром.
**Планировка**: редактор здания в 2D и 3D, расстановка мебели, оборудования, камер и светильников
по слоям, расчёты обзора камер и освещённости, проекты. **Учёт имущества**: инвентарные единицы
и остатки, места хранения, документы движения, стоимость, инвентаризация по QR-меткам с телефона.
Требования — `docs/TZ.md` (принято заказчиком 16.10.2026), что сделано по этапам — `docs/ACCEPTANCE.md`.

- Задачи: Plane, проект `DWG3D` - https://plane.mosai.pro/mosai/projects/8f656022-6097-4c22-8b21-3d9a197dfe4a/issues/
- Репозиторий: https://git.mosai.pro/tristanov.ab/dwg3d
- Основная ветка: `main`

## Быстрый старт

Нужны Docker, [uv](https://docs.astral.sh/uv/), Node.js 24. Команды — для bash (на Windows — Git Bash),
из корня репозитория; `serve`, `worker` и `npm run dev` — каждый в своём терминале.

```bash
# база разработки и тестов, один раз
docker run -d --name planuchet-devdb -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app \
  -e POSTGRES_DB=app -p 127.0.0.1:55432:5432 postgres:16-alpine

# сервер на :8010, при запуске сам обновляет базу; worker — фоновые задачи
cd server && uv sync
export APP_DATABASE_URL=postgresql+psycopg://app:app@localhost:55432/app
APP_SECURE_COOKIES=false uv run python -m app serve --port 8010
uv run python -m app worker
uv run python -m app create-admin          # первый администратор, печатает временный пароль
uv run python -m app sample polyclinic     # тестовое здание «Поликлиника»

# интерфейс на :5190, /api проксируется на :8010 (другой адрес — API_URL)
cd web && npm install && npm run dev
```

То же — конфигурации `server`, `worker`, `ui` в `.claude/launch.json` (`volume`, `volume-worker` —
стенд объёмов). Остальные конфигурации там устарели: не обращайте на них внимания, не запускайте и не правьте.

Проверки — ровно то, что запускает CI (`.gitlab-ci.yml`):

```bash
cd server && uv run ruff check app migrations tests
cd server && uv run pytest        # нужна база на :55432, тесты создают свою app_test
cd web && npm run typecheck && npm run lint && npm test && npx vite build
cd e2e && npx playwright test     # на работающей системе: E2E_URL, E2E_ADMIN, E2E_PASSWORD — e2e/README.md
```

## Структура

| Каталог | Что |
| --- | --- |
| `server/app/core` | ядро: настройки `APP_*`, база, вход, фоновые задачи, события, поиск |
| `server/app/modules/<имя>` | модуль: `api.py` — для других модулей, `routes.py` — HTTP, `models.py`, `module.py` |
| `server/migrations/versions` | миграции Alembic |
| `server/app/samples` | тестовые данные: `polyclinic`, `volume` (стенд объёмов ТЗ 8.1, на отдельной базе) |
| `web/src` | React + TypeScript + Vite + Tailwind; `editor/` — план и 3D, `help/` — встроенная справка |
| `e2e/tests` | Playwright: `stageN.spec.ts` — сценарии этапа N, `a11y` — доступность, `perf`/`volume` — замеры |
| `deploy/` | Docker Compose (db, app, worker, caddy, backup), `install.sh`, резервные копии |
| `legacy/`, `legacy2/` | прежние версии — только справка; CI их не проверяет |

Модули по уровням, снизу вверх (`server/app/modules/__init__.py`):
journal → access, files, system → building, catalog → planning, inventory → calc, link, projects → reports, transfer.

## Где что лежит

- Архитектура и потоки данных: `docs/architecture.md`
- Решения и их причины (ADR): `docs/decisions/` — прочитай перед изменением архитектуры
- Задачи в работе: `docs/tasks/` — файл на каждую задачу Plane: план, журнал, handoff
- Термины предметной области: `docs/glossary.md`
- Установка и обслуживание: `docs/INSTALL.md`; формат выгрузки: `docs/EXPORT.md`; 3D-модели каталога: `docs/3D-MODELS.md`

## Правила кода

- Модуль обращается только к модулям ниже по уровню и только через их `api`. Ядро от модулей не
  зависит. Таблицы модуля — в схеме базы с его именем, внешние ключи — к своим таблицам, ядру или
  модулям ниже. Проверяет `server/tests/test_architecture.py`. Новый модуль — в `TIERS` и `INSTALLED`.
- Каждое изменение данных пишется в журнал (`journal.api.record`) в той же транзакции.
- Схема базы меняется только миграцией `server/migrations/versions/ГГГГММДД_NNNN_что.py`;
  `tests/test_migrations.py` сверяет миграции с моделями.
- `docs/ADMIN.md` руками не правится: он собирается из `web/src/help/content.ts` командой
  `npm run admin-guide` в `web/`. Поменял поведение интерфейса — обнови справку.
- Код из `legacy/` и `legacy2/` не переносится и не правится (ТЗ 9.1).
- Комментарии, докстринги и тексты интерфейса — по-русски, со ссылкой на пункт ТЗ («ТЗ 9.2», «8.4 п. 2»).

## Как мы работаем (обязательно для любого агента)

1. Каждая задача — это задача в Plane с ID вида `ABC-123`, ветка `ABC-123-kratko` и файл `docs/tasks/ABC-123-kratko.md`.
2. Начало работы над задачей — навык `pickup`. Конец каждой сессии — навык `handoff`. Готово к ревью — навык `finish`.
3. Выбрали между вариантами (библиотека, схема данных, протокол, важный компромисс) — запиши решение навыком `adr`.
4. Коммиты маленькие. Тема — что сделано, тело — почему. Трейлеры:
   - `Refs: ABC-123` (хук добавит сам по имени ветки);
   - `Assisted-by: <агент> / <модель>`, если код писал агент.
5. Всё, что пригодится команде, — в репозиторий: файл задачи, ADR, `docs/`, этот файл. Не в личную память агента и не в чат.
6. Перед `finish` линтеры, типы и тесты зелёные локально.
7. Человек читает весь diff перед merge и должен уметь объяснить каждое изменение.

## Нельзя

- Коммитить секреты, `.env`, дампы с персональными данными.
- Коммитить чертежи заказчика (`*.dwg`, `Поэтажные планы *.dxf|pdf`) — это данные, не код.
- Менять публичные API и схему данных без ADR.
- Отключать или ослаблять проверки CI, чтобы «пройти».
- Пушить в основную ветку напрямую.

## Навыки

Общие навыки команды лежат в `.agents/skills/` (их читает Codex: вызов `$pickup`).
Копия для Claude Code — `.claude/skills/` (вызов `/pickup`). Её обновляет `scripts/sync-skills.ps1` или `scripts/sync-skills.sh`; руками копию не правьте.

| Навык | Когда |
| --- | --- |
| `onboard` | Первый вход в проект или возвращение после перерыва |
| `pickup` | Начало сессии: взять новую или чужую задачу |
| `handoff` | Конец каждой сессии и передача задачи |
| `adr` | Принято решение с вариантами |
| `finish` | Задача готова к ревью |
