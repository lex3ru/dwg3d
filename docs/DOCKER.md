# Запуск в Docker

Весь стек описан в `docker-compose.yml`:

| сервис   | что делает                                                        |
|----------|-------------------------------------------------------------------|
| `web`    | Caddy: собранный интерфейс и единая точка входа (`/api`, `/auth`) |
| `api`    | FastAPI (`dwg3d.api`)                                             |
| `worker` | очередь сборок DWG → 3D; масштабируется `--scale worker=N`        |
| `db`     | PostgreSQL                                                        |
| `s3`     | RustFS — S3-совместимое хранилище чертежей, моделей, экспорта     |
| `backup` | раз в сутки: дамп базы и зеркало файлов в `DWG3D_BACKUP_DIR`      |
| `keycloak` | вход (OpenID Connect), realm `dwg3d`, по адресу `/auth`         |

## Первый запуск

```bash
cp .env.example .env      # пароли, адрес сайта (DWG3D_PUBLIC_URL)
docker compose up -d --build
```

Интерфейс: `http://localhost:8088` (порт — `DWG3D_HTTP_PORT`). Первый вход —
`DWG3D_ADMIN_USER` / `DWG3D_ADMIN_PASSWORD` (Keycloak попросит сменить пароль);
это глобальный администратор.

## Keycloak

Realm `dwg3d` импортируется при первом старте из
`deploy/keycloak/dwg3d-realm.json` (переменные `${…}` берутся из окружения
сервиса); если realm уже есть, файл не читается. Таблицы Keycloak лежат в
схеме `keycloak` той же базы (попадают в резервные копии).

- Консоль: `$DWG3D_PUBLIC_URL/auth/admin/` (`KEYCLOAK_ADMIN` /
  `KEYCLOAK_ADMIN_PASSWORD`, realm `master`).
- Пользователи: realm `dwg3d` → Users. Глобальные роли — realm roles `admin`
  и `catalog_admin`; доступ к проектам выдаётся в самом приложении.
- Вход через корпоративный каталог (LDAP/AD) или другой IdP настраивается в
  Keycloak (User federation / Identity providers) — приложение не меняется.
- Смена адреса сайта: `DWG3D_PUBLIC_URL` в `.env` и Valid redirect URIs
  клиента `dwg3d` в консоли (импорт уже существующего realm не повторяется).

## Файлы

Чертежи, построенные модели, экспорт и загруженные модели каталога хранятся
в S3 (сервис `s3`, бакет `DWG3D_S3_BUCKET`). Сервер можно заменить любым
S3-совместимым (MinIO, SeaweedFS, Yandex Object Storage, AWS) — достаточно
поменять `DWG3D_S3_ENDPOINT` и ключи у `api`, `worker`, `backup`.

`api` и `worker` держат в томе `scratch` только рабочие копии: сборщик
скачивает исходник и прошлый результат (кэш планов, сконвертированный DXF),
строит модель и отправляет обратно только изменившиеся файлы.

Перенос файлов, накопленных до перехода на S3 (каталог `data/`):

```bash
docker compose run --rm --no-deps -e DWG3D_DATA=/import -v "$PWD/data":/import:ro \
  api python -m dwg3d files upload
```

## Резервные копии

Сервис `backup` раз в сутки пишет в `DWG3D_BACKUP_DIR` (по умолчанию
`./backups`):

- `db/dwg3d-<дата>.dump` — дамп PostgreSQL (хранятся последние
  `DWG3D_BACKUP_KEEP`);
- `files/` — зеркало хранилища файлов.

Восстановление (дампы делает `pg_dump` образа приложения — им же и
восстанавливаем):

```bash
docker compose stop web api worker keycloak backup
docker compose run --rm --no-deps -v "$PWD/backups/db":/dump:ro backup \
  sh -c 'pg_restore --clean --if-exists --no-owner --dbname "$(echo "$DWG3D_DATABASE_URL" | sed s/+psycopg//)" /dump/dwg3d-<дата>.dump'
docker compose run --rm --no-deps -v "$PWD/backups/files":/restore:ro api python -m dwg3d files restore /restore
docker compose up -d
```

Предупреждение `transaction_timeout` при восстановлении в PostgreSQL 16 —
безвредно (параметр появился в 17).

Для развёртывания на сервере — папка `_deploy/` (свой `README.md`).

## HTTPS

Укажите в `.env` доменное имя: `DWG3D_SITE=plan.example.com`, откройте
порты 80 и 443 (`DWG3D_HTTP_PORT=80`, `DWG3D_HTTPS_PORT=443`) — Caddy сам
получит и продлит сертификат.

## Конвертер DWG

В образ `api` собран LibreDWG (`dwg2dxf`, `dxf2dwg`). ODA File Converter
точнее, но его лицензия не позволяет распространять его в образе. Если он
у вас есть, смонтируйте его в контейнеры `api` и `worker` (например, через
`docker-compose.override.yml`) и укажите путь в `DWG3D_ODA`.

## Разработка

Приложение можно запускать и без контейнеров, а в Docker держать только
инфраструктуру:

```bash
docker compose up -d db s3
cd backend && uv run uvicorn dwg3d.api:app --port 8765
cd frontend && npm run dev
```

Без `DWG3D_S3_ENDPOINT` локальный сервер хранит файлы в каталоге `data/`
(как раньше); тесты S3-режима (`tests/test_files.py`) используют сервис `s3`.

Вход при локальном запуске — через Keycloak из compose (адрес
`http://localhost:5174` уже разрешён в realm для возврата после входа):

```bash
docker compose up -d                        # db, s3, keycloak (и остальное)
cd backend && DWG3D_OIDC_ISSUER=http://localhost:8088/auth/realms/dwg3d \
  DWG3D_OIDC_INTERNAL=http://127.0.0.1:8180/auth/realms/dwg3d \
  DWG3D_OIDC_CLIENT_SECRET=dev-client-secret uv run uvicorn dwg3d.api:app --port 8765
```

или без входа: `DWG3D_AUTH=off`. Тест с настоящим Keycloak —
`tests/test_keycloak.py` (пропускается, если Keycloak не запущен).
