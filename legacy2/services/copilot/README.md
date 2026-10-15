# copilot

Копилот: ИИ-помощник, который отвечает на вопросы о здании, объектах, людях и правах и предлагает
изменения — всё через запросы остальных сервисов **с токеном пользователя**. Замысел, инструменты и
план работ — в [docs/COPILOT.md](../../docs/COPILOT.md).

## Запуск

```bash
docker compose -f deploy/docker-compose.yml up -d db db-init nats keycloak   # инфраструктура
cd services/copilot
uv run python -m twin_chassis.migrate                                        # миграции
uv run uvicorn app.main:build --factory --port 8000
```

В общем стеке: `docker compose -f deploy/docker-compose.yml up -d --build copilot`.

## Настройки

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `TWIN_DATABASE_URL` | база `copilot` стека разработки | своя база сервиса |
| `TWIN_NATS_URL` | `nats://127.0.0.1:4223` | шина событий |
| `TWIN_OIDC_ISSUER`, `TWIN_OIDC_INTERNAL` | realm `twin` стека разработки | кто выпускает токены |
| `TWIN_SERVICES` | `access=http://access:8000,…` | адреса сервисов, к которым ходит с токеном пользователя |
| `TWIN_COPILOT_SECRET` | секрет сервиса | шифрует ключ модели в базе |

Сама модель (адрес OpenAI-совместимого API, ключ, имя модели, лимиты) задаётся администратором системы
через `PUT /settings` — в интерфейсе на странице «Состояние системы». Модель на этой же машине из
контейнера видна как `http://host.docker.internal:<порт>/v1`.

## Запросы

`/api/copilot/v1` — см. `contracts/openapi/copilot.v1.json` и docs/CONTRACTS.md раздел 10:
`/status`, `/settings`, `/settings/check`, `/chats`, `/chats/{id}`, `/chats/{id}/messages` (ответ потоком SSE).

## Устройство

- `app/config.py` — настройки модели (ключ зашифрован), учёт запросов в день.
- `app/llm.py` — один запрос к `/chat/completions` потоком, с инструментами.
- `app/tools/` — инструменты: `reading.py` — чтение. Каждый — запрос к сервису с токеном пользователя;
  отказ сервиса (403/404) возвращается модели текстом.
- `app/agent.py` — цикл ответа: модель → инструменты → модель; сообщения пишутся в базу по ходу.
- `app/prompt.py` — системная подсказка и строка «что открыто у пользователя».

## Тесты

`uv run ruff check . && uv run pytest` — остальные сервисы и модель заменены подставными
(`tests/conftest.py`: `World`, `FakeModel`).
