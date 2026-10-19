#!/usr/bin/env bash
# Restore a backup created by backup_database.sh.
# RESTORE_DATABASE selects the target database. The default is the application
# database, which replaces its current data.
# RESTORE_UPLOADS=0 leaves the upload volume unchanged.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: RESTORE_CONFIRM=glidecrm $0 backups/glidecrm-TIMESTAMP.tar.gz[.enc]" >&2
  exit 2
fi

if [[ "${RESTORE_CONFIRM:-}" != "glidecrm" ]]; then
  echo "Set RESTORE_CONFIRM=glidecrm to acknowledge a destructive restore." >&2
  exit 2
fi

backup_file="$1"
if [[ ! -f "${backup_file}" ]]; then
  echo "Backup not found: ${backup_file}" >&2
  exit 2
fi

workdir="$(mktemp -d)"
cleanup() {
  rm -rf "${workdir}"
}
trap cleanup EXIT

source_file="${backup_file}"
if [[ "${backup_file}" == *.enc ]]; then
  if [[ -z "${BACKUP_PASSPHRASE:-}" ]]; then
    echo "Set BACKUP_PASSPHRASE to decrypt ${backup_file}." >&2
    exit 2
  fi
  source_file="${workdir}/archive.tar.gz"
  openssl enc -d -aes-256-cbc -pbkdf2 \
    -pass env:BACKUP_PASSPHRASE \
    -in "${backup_file}" \
    -out "${source_file}"
fi

if [[ "${source_file}" == *.sql.gz ]]; then
  gzip --test "${source_file}"
  cp "${source_file}" "${workdir}/database.sql.gz"
  restore_uploads=0
else
  tar -xzf "${source_file}" -C "${workdir}"
  gzip --test "${workdir}/database.sql.gz"
  restore_uploads="${RESTORE_UPLOADS:-1}"
fi

target_database="${RESTORE_DATABASE:-}"
if [[ -n "${target_database}" ]]; then
  if [[ ! "${target_database}" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "RESTORE_DATABASE must contain only letters, numbers, and underscores." >&2
    exit 2
  fi
  docker compose exec -T -e "TARGET_DATABASE=${target_database}" database \
    sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "CREATE DATABASE IF NOT EXISTS \`$TARGET_DATABASE\` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"'
  gzip --decompress --stdout "${workdir}/database.sql.gz" \
    | docker compose exec -T -e "TARGET_DATABASE=${target_database}" database \
      sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$TARGET_DATABASE"'
else
  gzip --decompress --stdout "${workdir}/database.sql.gz" \
    | docker compose exec -T database sh -c \
      'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot "$MYSQL_DATABASE"'
fi

if [[ "${restore_uploads}" == "1" ]]; then
  docker compose exec -T web tar -C /app -xzf - <"${workdir}/uploads.tar.gz"
fi

echo "Restored ${backup_file}"
