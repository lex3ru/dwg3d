# __service__

__title__.

> Создан из шаблона. Замените образец (заметки, `notes`) настоящими
> сущностями сервиса и опишите их здесь.

## Запуск

```bash
docker compose -f deploy/docker-compose.yml up -d db db-init nats keycloak   # инфраструктура
cd services/__service__
uv run python -m twin_chassis.migrate                                        # миграции
uv run uvicorn app.main:build --factory --port 8000
```

В общем стеке: `docker compose -f deploy/docker-compose.yml up -d --build __service__`.

## Настройки

| Переменная | По умолчанию | Что задаёт |
|---|---|---|
| `TWIN_DATABASE_URL` | база `__service__` стека разработки | своя база сервиса |
| `TWIN_NATS_URL` | `nats://127.0.0.1:4223` | шина событий |
| `TWIN_OIDC_ISSUER` | realm `twin` стека разработки | кто выпускает токены |
| `TWIN_OIDC_INTERNAL` | как `TWIN_OIDC_ISSUER` | тот же realm по внутреннему адресу |
| `TWIN_CONTRACTS` | каталог `contracts/` репозитория | контракты |

## Запросы

`/api/__service__/v1` — см. `contracts/openapi/__service__.v1.json`
(при запущенном сервисе: `/api/__service__/v1/docs`).

## События

| Публикует | Когда |
|---|---|
| `__service__.note.created` | создана заметка |

| Получает | Реакция |
|---|---|
| `__service__.note.created` | обработчик `echo`: отмечает заметку (образец обработчика) |

## Тесты

```bash
uv run ruff check . && uv run pytest
```

Нужны PostgreSQL и NATS стека разработки; другие сервисы не нужны.
После намеренного изменения запросов:
`uv run python -m twin_chassis.contracts __service__`.
