# twin-chassis

Общая основа сервисов цифрового двойника: то, что все сервисы обязаны делать
одинаково (docs/CONTRACTS.md, раздел 1).

| Модуль | Что даёт |
|---|---|
| `app.create_app` | приложение FastAPI сервиса: адреса `/api/<сервис>/v1`, `/healthz`, ошибки, журнал, шина |
| `auth` | проверка токена Keycloak, `current_identity`, `require_admin` |
| `errors.Problem` | ошибки в `application/problem+json` |
| `db` | своя база сервиса, таблицы `outbox` и `inbox`, `uuid7()` |
| `events.emit` | событие в `outbox` в транзакции изменения, с проверкой по `contracts/events/` |
| `bus.Bus` | публикация `outbox` в NATS JetStream; обработчики с защитой от повторной доставки |
| `log` | журнал в JSON со сквозным идентификатором запроса |
| `migrate` | миграции Alembic сервиса: `python -m twin_chassis.migrate` |
| `contracts` | запись запросов сервиса в `contracts/openapi/` |
| `testing` | для тестов: временная база, подписанные токены, проверка контракта |
| `pdf` | документы PDF: шрифт с кириллицей (DejaVu, `fonts/`), QR-код, подбор размера строки — нужна зависимость `twin-chassis[pdf]` |

Сервисы подключают пакет по пути (`[tool.uv.sources]` в `pyproject.toml`).
Новый сервис создаётся командой `tools/new-service <имя>`.

Адрес системы для ссылок, которые сервисы пишут сами (QR-метки), — `TWIN_PUBLIC_URL` (`settings.public_url`,
по умолчанию `http://localhost:8090`).
