#!/bin/sh
# Резервные копии по расписанию BACKUP_AT (cron); первая — сразу после установки.
set -eu
env | grep -E '^(PG|KEEP_|TZ=)' | sed 's/^/export /; s/=\(.*\)$/="\1"/' > /etc/backup.env
echo "$BACKUP_AT . /etc/backup.env; /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1" > /etc/crontabs/root
if [ ! -f /backups/last.json ]; then
  until pg_isready -q; do sleep 2; done
  /usr/local/bin/backup.sh || true
fi
exec crond -f -l 8
