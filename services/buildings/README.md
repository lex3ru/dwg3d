# buildings

Здание: этажи и помещения.

> Создан из шаблона. Замените образец (заметки, `notes`) настоящими
> сущностями сервиса и опишите их здесь.

## Запуск

```bash
docker compose -f deploy/docker-compose.yml up -d db db-init nats keycloak   # инфраструктура
cd services/buildings
uv run python -m twin_chassis.migrate                                        # миграции
uv run uvicorn app.main:build --factory --port 8000
```

В общем стеке: `docker compose -f deploy/docker-compose.yml up -d --build buildings`.

## Настройки

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `TWIN_DATABASE_URL` | база `buildings` стека разработки | своя база сервиса |
| `TWIN_NATS_URL` | `nats://127.0.0.1:4223` | шина событий |
| `TWIN_OIDC_ISSUER` | realm `twin` стека разработки | кто выпускает токены |
| `TWIN_OIDC_INTERNAL` | как `TWIN_OIDC_ISSUER` | тот же realm по внутреннему адресу |
| `TWIN_CONTRACTS` | каталог `contracts/` репозитория | контракты |

## Запросы

`/api/buildings/v1` — см. `contracts/openapi/buildings.v1.json`
(при запущенном сервисе: `/api/buildings/v1/docs`).

## События

| Публикует | Когда |
|---|---|
| `buildings.note.created` | создана заметка |

| Получает | Реакция |
|---|---|
| `buildings.note.created` | обработчик `echo`: отмечает заметку (образец обработчика) |

## Тесты

```bash
uv run ruff check . && uv run pytest
```

Нужны PostgreSQL и NATS стека разработки; другие сервисы не нужны.
После намеренного изменения запросов:
`uv run python -m twin_chassis.contracts buildings`.
