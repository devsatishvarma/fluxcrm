#!/usr/bin/env bash
# Database and upload backup. Encrypt with BACKUP_PASSPHRASE before the file
# leaves this machine. A local gzip file alone is not an off-host backup.
set -euo pipefail

backup_dir="${BACKUP_DIR:-backups}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
staging="${backup_dir}/.staging-${timestamp}"
archive="${backup_dir}/glidecrm-${timestamp}.tar.gz"

mkdir -p "${staging}"
umask 077

docker compose exec -T database sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --single-transaction --routines --triggers --set-gtid-purged=OFF -uroot "$MYSQL_DATABASE"' \
  | gzip -9 >"${staging}/database.sql.gz"
gzip --test "${staging}/database.sql.gz"

docker compose exec -T web tar -C /app -czf - uploads >"${staging}/uploads.tar.gz"
gzip --test "${staging}/uploads.tar.gz"

printf 'created_at=%s\ndatabase=database.sql.gz\nuploads=uploads.tar.gz\n' \
  "${timestamp}" >"${staging}/manifest.txt"

tar -C "${staging}" -czf "${archive}" database.sql.gz uploads.tar.gz manifest.txt
rm -rf "${staging}"

if [[ -n "${BACKUP_PASSPHRASE:-}" ]]; then
  openssl enc -aes-256-cbc -pbkdf2 -salt \
    -pass env:BACKUP_PASSPHRASE \
    -in "${archive}" \
    -out "${archive}.enc"
  rm -f "${archive}"
  echo "Created ${archive}.enc"
else
  echo "Created ${archive}"
  echo "Set BACKUP_PASSPHRASE before copying this backup off the host."
fi
