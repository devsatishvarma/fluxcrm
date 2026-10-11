#!/usr/bin/env bash
set -euo pipefail

backup_dir="${BACKUP_DIR:-backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="${backup_dir}/fluxcrm-${timestamp}.sql.gz"

mkdir -p "${backup_dir}"
umask 077

docker compose exec -T database sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --single-transaction --routines --triggers --set-gtid-purged=OFF -uroot "$MYSQL_DATABASE"' \
  | gzip -9 >"${output}"

gzip --test "${output}"
echo "Created ${output}"
