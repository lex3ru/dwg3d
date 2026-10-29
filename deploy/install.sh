#!/usr/bin/env bash
# Установка и обновление одной командой (8.5 п. 1):
#
#   ./deploy/install.sh [адрес сервера]
#
# При первой установке можно задать порты и каталог копий переменными окружения:
#   HTTP_PORT=8080 HTTPS_PORT=8443 BACKUP_DIR=/mnt/backup/planuchet ./deploy/install.sh
#
# Первый запуск создаёт deploy/.env (пароль базы, адрес, порты, каталог копий), собирает
# и запускает систему и заводит первого администратора — его временный пароль печатается
# в конце. Повторный запуск — обновление: сначала резервная копия (8.3 п. 5), потом новая
# версия; данные переносятся сами (миграции базы при запуске приложения).
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\n\033[31mОшибка: %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "нет Docker. Установите Docker Engine и Docker Compose (docs/INSTALL.md)."
docker compose version >/dev/null 2>&1 || die "нет Docker Compose v2 (команда «docker compose»)."
docker info >/dev/null 2>&1 || die "Docker не запущен или у пользователя нет к нему доступа (нужна группа docker или sudo)."

if [ ! -f .env ]; then
  address="${1:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
  [ -n "$address" ] || die "не удалось определить адрес сервера — передайте его: ./install.sh 192.168.1.10"
  password="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
  http_port="${HTTP_PORT:-80}"
  https_port="${HTTPS_PORT:-443}"
  url="https://$address"
  [ "$https_port" = 443 ] || url="$url:$https_port"
  say "Первая установка. Адрес системы: $url"
  cat > .env <<ENV
# Настройки установки. Изменили — запустите install.sh ещё раз.

# адреса, по которым система открывается (IP или имя; несколько — через запятую)
SITE_ADDRESS=$address
# откуда перенаправлять http:// (с портом, если HTTPS_PORT не 443)
PUBLIC_URL=$url
# internal — свой сертификат для локальной сети; адрес почты — сертификат Let's Encrypt
# (только для имени, открытого из интернета, 8.5 п. 3)
CADDY_TLS=internal
HTTP_PORT=$http_port
HTTPS_PORT=$https_port

# резервные копии — на другом диске, чем данные (8.3 п. 3)
BACKUP_DIR=${BACKUP_DIR:-$(pwd)/backups}
BACKUP_AT="0 2 * * *"
KEEP_DAILY=30
KEEP_MONTHLY=12

# процессов приложения — по числу ядер сервера: тяжёлый отчёт не задерживает остальных
APP_WORKERS=4
# запросов одновременно на процесс, остальные ждут очереди; соединений с базой всего —
# APP_WORKERS × (APP_DB_POOL + 3) + 10, не больше 200 (docs/INSTALL.md, «Производительность»)
APP_DB_POOL=10

TZ=Europe/Moscow
POSTGRES_PASSWORD=$password
ENV
  chmod 600 .env
  fresh=1
else
  say "Обновление установленной системы."
  fresh=0
fi

set -a; . ./.env; set +a
mkdir -p "$BACKUP_DIR"

if [ "$fresh" = 0 ] && [ -n "$(docker compose ps -q backup 2>/dev/null)" ]; then
  say "Резервная копия перед обновлением…"
  docker compose exec -T backup backup.sh || die "резервная копия не удалась — обновление отменено."
fi

say "Сборка…"
docker compose build --pull
say "Запуск…"
docker compose up -d --wait --remove-orphans

admin="$(docker compose exec -T app python -m app create-admin --name 'Администратор' 2>/dev/null | grep -v ' INFO ' || true)"

say "Готово. Система: $PUBLIC_URL"
if printf '%s' "$admin" | grep -q 'Временный пароль'; then
  printf '%s\n' "$admin"
  echo "Войдите с именем «admin» и этим паролем; система попросит придумать свой."
fi
if [ "$CADDY_TLS" = internal ]; then
  echo "Сертификат свой: браузер предупредит, пока на устройство не поставлен корневой"
  echo "сертификат — его можно скачать по адресу http://${SITE_ADDRESS%%,*}:${HTTP_PORT}/ca.crt (docs/INSTALL.md)."
fi
echo "Резервные копии: $BACKUP_DIR (каждый день по расписанию «$BACKUP_AT»)."
