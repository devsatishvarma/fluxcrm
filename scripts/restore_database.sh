#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: RESTORE_CONFIRM=fluxcrm $0 backups/fluxcrm-TIMESTAMP.sql.gz" >&2
  exit 2
fi

if [[ "${RESTORE_CONFIRM:-}" != "fluxcrm" ]]; then
  echo "Set RESTORE_CONFIRM=fluxcrm to acknowledge destructive restore." >&2
  exit 2
fi

backup_file="$1"
if [[ ! -f "${backup_file}" ]]; then
  echo "Backup not found: ${backup_file}" >&2
  exit 2
fi

gzip --test "${backup_file}"
gzip --decompress --stdout "${backup_file}" \
  | docker compose exec -T database sh -c \
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE"'

echo "Restored ${backup_file}"
