# «Поэтажные планы → 3D» — развёртывание на сервере

Система: веб-приложение, которое строит 3D-модели зданий из поэтажных планов
DWG/DXF, с проектами, слоями (мебель, видеонаблюдение, маршруты людей, СКС,
пожарная сигнализация, СКУД, Wi-Fi), спецификациями и входом через Keycloak.
Всё работает в Docker-контейнерах.

## Что в этой папке

| | |
|---|---|
| `docker-compose.yml` | весь стек для сервера |
| `.env.example` | настройки: адрес, пароли, секреты — скопировать в `.env` |
| `keycloak/dwg3d-realm.json` | realm Keycloak: клиент приложения, роли, первый администратор (импортируется при первом запуске) |
| `src/backend`, `src/frontend` | исходники для сборки образов приложения (`src/VERSION` — коммит) |
| `scripts/gen-secrets.sh` | генерирует пароли и секреты для `.env` |
| `scripts/save-images.sh`, `load-images.sh` | перенос готовых образов на сервер без интернета |
| `scripts/backup-now.sh`, `restore.sh` | резервная копия сейчас; восстановление |

## Состав стека

```
                 Интернет
                    │ 80 / 443
              ┌─────▼─────┐
              │    web    │  Caddy: интерфейс, TLS (Let's Encrypt), прокси /api и /auth
              └──┬─────┬──┘
          /api   │     │  /auth
          ┌──────▼┐   ┌▼─────────┐
          │  api  │   │ keycloak │  вход (OpenID Connect)
          └┬──┬───┘   └────┬─────┘
           │  │ очередь    │
           │ ┌▼──────┐     │
           │ │worker │     │     сборка 3D-моделей (можно масштабировать)
           │ └┬──────┘     │
       ┌───▼──▼──┐   ┌─────▼─┐
       │   s3    │   │  db   │   RustFS (файлы) · PostgreSQL (данные + схема keycloak)
       └─────────┘   └───────┘
           backup — раз в сутки: дамп базы + зеркало файлов в ./backups
```

Наружу открыт только `web` (порты 80 и 443). База, хранилище и Keycloak
доступны только внутри сети docker.

## Требования к серверу

- Linux x86-64, Docker Engine 24+ с плагином `docker compose` v2.
- 4 ядра CPU, 8 ГБ RAM (сборка модели большого здания занимает до 2–3 ГБ
  памяти и минуту процессора), диск — от 50 ГБ (чертежи и модели: 20–100 МБ
  на здание; плюс резервные копии).
- Доменное имя с DNS-записью на сервер и открытые входящие 80 и 443 — для
  автоматического HTTPS. Либо внешний прокси/балансировщик с TLS (см. ниже).
- Для сборки образов на сервере — доступ в интернет (PyPI, npm, GitHub,
  Docker Hub, quay.io). Без интернета — перенесите готовые образы (ниже).

## Установка

```bash
# 1. Разложить папку на сервере, например в /opt/dwg3d
cd /opt/dwg3d

# 2. Настройки
cp .env.example .env
scripts/gen-secrets.sh >> .env     # случайные пароли и секреты допишутся в конец
nano .env                          # DWG3D_PUBLIC_URL, DWG3D_SITE; удалить пустые дубли паролей выше
chmod 600 .env

# 3. Образы (5–15 минут: LibreDWG собирается из исходников)
docker compose build

# 4. Запуск
docker compose up -d
docker compose ps                  # все сервисы Up, api — healthy
```

Первый старт: `api` создаёт схему базы, затем стартует Keycloak и
импортирует realm (1–2 минуты). Проверка:

```bash
curl -s https://plans.example.com/api/health          # {"ok": true, ...}
curl -s https://plans.example.com/auth/realms/dwg3d/.well-known/openid-configuration | head -c 200
```

Откройте `DWG3D_PUBLIC_URL` и войдите: логин `DWG3D_ADMIN_USER`, пароль
`DWG3D_ADMIN_PASSWORD`. Keycloak попросит сменить пароль. Это глобальный
администратор системы: видит все проекты и правит каталог оборудования.

### Обязательные настройки `.env`

| Переменная | |
|---|---|
| `DWG3D_PUBLIC_URL` | адрес для пользователей: `https://plans.example.com` (без `/` в конце). На него Keycloak возвращает после входа |
| `DWG3D_SITE` | доменное имя — Caddy сам выпустит сертификат; `:80` — если TLS завершает внешний прокси |
| `POSTGRES_PASSWORD`, `DWG3D_S3_SECRET_KEY` | пароли базы и хранилища |
| `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD` | администратор консоли Keycloak |
| `DWG3D_OIDC_CLIENT_SECRET` | секрет клиента приложения в Keycloak |
| `DWG3D_ADMIN_USER`, `DWG3D_ADMIN_PASSWORD` | первый пользователь приложения (временный пароль) |
| `DWG3D_SECRET` | ключ подписи (длинная случайная строка) |

`docker compose` откажется стартовать, если что-то из обязательного не задано.

> `KEYCLOAK_ADMIN_PASSWORD`, `DWG3D_OIDC_CLIENT_SECRET`, `DWG3D_ADMIN_*`
> читаются только при **первом** запуске Keycloak. Позже меняйте их в консоли
> Keycloak (а секрет клиента — и в консоли, и в `.env`, затем
> `docker compose up -d api worker`).

### За внешним прокси (TLS снаружи)

`DWG3D_SITE=:80`, `DWG3D_HTTPS_PORT` можно не открывать, `DWG3D_HTTP_PORT` —
порт, на который проксирует балансировщик. `DWG3D_PUBLIC_URL` — внешний
`https://…` адрес. Прокси должен передавать `Host`, `X-Forwarded-Proto: https`,
`X-Forwarded-For` и находиться в частной сети (10/8, 172.16/12, 192.168/16) —
такие заголовки web принимает. Лимит тела запроса на прокси — не меньше
`DWG3D_MAX_UPLOAD_MB` (загрузка чертежей), таймаут — от 300 с.

### Без интернета на сервере

На машине с интернетом (в этой же папке):

```bash
cp .env.example .env      # достаточно имён образов и тега
scripts/save-images.sh    # images/dwg3d-images.tar.gz, ~1,5 ГБ
```

Скопируйте папку на сервер (вместе с `images/`), затем:

```bash
scripts/load-images.sh
docker compose up -d --no-build
```

Для своего реестра: задайте `DWG3D_IMAGE_API`, `DWG3D_IMAGE_WEB`,
`DWG3D_TAG`, выполните `docker compose build && docker compose push api web`,
на сервере — `docker compose pull && docker compose up -d --no-build`.

## Пользователи и доступ

- Учётные записи — в Keycloak: `DWG3D_PUBLIC_URL/auth/admin/` → realm
  **dwg3d** → Users. Регистрация отключена, пользователей заводит администратор
  (или подключается LDAP/AD: User federation; SSO: Identity providers).
- Глобальные роли — Realm roles: `admin` (все проекты, каталог) и
  `catalog_admin` (правка каталога оборудования). Остальным ролей не нужно.
- Доступ к проектам выдаётся в самом приложении: страница проекта →
  «Участники» (владелец, редактор, просмотр). Любой вошедший может создать
  свой проект.
- Смена адреса сайта: `DWG3D_PUBLIC_URL`/`DWG3D_SITE` в `.env`,
  `docker compose up -d`, и в консоли Keycloak: Clients → dwg3d → Valid
  redirect URIs и Valid post logout redirect URIs (realm повторно не импортируется).
- Консоль Keycloak доступна по тому же адресу `/auth/admin/`. Если её нужно
  закрыть снаружи — ограничьте путь `/auth/admin` на внешнем прокси или
  межсетевом экране (пользователям нужен только `/auth/realms/dwg3d/…`).

## Резервные копии

Сервис `backup` раз в сутки пишет в `DWG3D_BACKUP_DIR` (по умолчанию `./backups`):

- `db/dwg3d-<дата>.dump` — дамп PostgreSQL, включая пользователей Keycloak
  (хранятся последние `DWG3D_BACKUP_KEEP`);
- `files/` — зеркало хранилища (чертежи, модели, выгрузки, модели каталога).

Копируйте `backups/` за пределы сервера (rsync, S3, ленточная система).
Копия прямо сейчас — `scripts/backup-now.sh`.

Восстановление (на этом же или новом сервере с тем же `.env`):

```bash
docker compose up -d                        # стек должен быть запущен
scripts/restore.sh backups/db/dwg3d-20261001-030000.dump
```

## Обновление

```bash
cd /opt/dwg3d
scripts/backup-now.sh                        # на всякий случай
# заменить src/ (или загрузить новые образы) новой версией
docker compose build && docker compose up -d
```

Схема базы обновляется сама при старте `api` (миграции Alembic).
Параллельно работающие старые и новые версии не нужны: простой — секунды.

## Эксплуатация

```bash
docker compose ps                            # состояние
docker compose logs -f api worker            # журналы (ротация: 5 × 20 МБ на сервис)
docker compose up -d --scale worker=3        # больше параллельных сборок моделей
docker compose exec api python -m dwg3d user list   # кто входил
```

- Проверка живости для мониторинга: `GET /api/health` → `{"ok": true, "db": true,
  "queue": {...}}` (без входа).
- Сборка, прерванная падением контейнера, через 2 минуты помечается ошибкой;
  пользователь может запустить её снова.
- Тома: `pgdata` (база), `s3data` (файлы), `caddy-data` (сертификаты),
  `scratch` (временные рабочие копии — можно очищать).

## DWG: необязательный ODA File Converter

DWG читается встроенным LibreDWG. Для **сохранения** чертежа с правками и
слоями в формате DWG нужен ODA File Converter (бесплатный, но
распространять его в образе лицензия не позволяет; без него пользователи
скачивают DXF — AutoCAD его открывает). Установка: скачайте Linux-версию с
opendesign.com, положите на сервер и подключите к `api` и `worker` через
`docker-compose.override.yml`:

```yaml
services:
  api:
    volumes: ["/opt/oda:/opt/oda:ro"]
  worker:
    volumes: ["/opt/oda:/opt/oda:ro"]
```

и в `.env`: `DWG3D_ODA=/opt/oda/ODAFileConverter`.

## Безопасность

- `.env` содержит все секреты: права `600`, не хранить в git.
- Входящий трафик — только 80/443. Сессии — cookie `HttpOnly; Secure;
  SameSite=Lax`; токены Keycloak на клиент не передаются.
- DWG разбирается внешним конвертером под лимитами памяти и CPU внутри
  непривилегированного контейнера.
- Защита от перебора паролей и политика паролей — настройки realm в Keycloak
  (Realm settings → Security defenses / Authentication → Policies).

## Для разработчиков: подготовка папки

`src/` не хранится в git — перед передачей заполните его из репозитория
(`src/VERSION` — коммит):

```bash
_deploy/scripts/refresh-src.sh
tar czf dwg3d-deploy.tar.gz --exclude=_deploy/.env --exclude=_deploy/backups _deploy
```
