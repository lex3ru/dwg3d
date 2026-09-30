# Запуск в Docker

Весь стек описан в `docker-compose.yml`:

| сервис   | что делает                                                        |
|----------|-------------------------------------------------------------------|
| `web`    | Caddy: собранный интерфейс и единая точка входа (`/api`, `/auth`) |
| `api`    | FastAPI (`dwg3d.api`)                                             |
| `worker` | очередь сборок DWG → 3D; масштабируется `--scale worker=N`        |
| `db`     | PostgreSQL                                                        |

## Первый запуск

```bash
cp .env.example .env      # пароли, адрес сайта, uid:gid владельца каталога данных
docker compose up -d --build
docker compose exec api python -m dwg3d user add admin --role catalog_admin
```

Интерфейс: `http://localhost:8088` (порт — `DWG3D_HTTP_PORT`).

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
docker compose up -d db
cd backend && uv run uvicorn dwg3d.api:app --port 8765
cd frontend && npm run dev
```
