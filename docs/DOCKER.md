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

## Первый запуск

```bash
cp .env.example .env      # пароли, адрес сайта, uid:gid владельца каталога данных
docker compose up -d --build
docker compose exec api python -m dwg3d user add admin --role catalog_admin
```

Интерфейс: `http://localhost:8088` (порт — `DWG3D_HTTP_PORT`).

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

Восстановление:

```bash
docker compose exec -T db pg_restore -c -U dwg3d -d dwg3d < backups/db/dwg3d-<дата>.dump
docker compose run --rm --no-deps -v "$PWD/backups/files":/restore:ro api python -m dwg3d files restore /restore
```

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
