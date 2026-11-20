#!/usr/bin/env bash
# Daily encrypted backup. The archive stays on this machine for 14 days.
# When BACKUP_RCLONE_DEST is set, the same encrypted file is copied off the
# server. Install rclone and configure the remote before setting that variable.
# Confirm the flags in https://rclone.org/commands/rclone_copy/ and
# https://rclone.org/commands/rclone_delete/ before relying on a restore.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "${root}"

if [[ -z "${BACKUP_PASSPHRASE:-}" ]]; then
  echo "Set BACKUP_PASSPHRASE. An unencrypted archive must not leave the server." >&2
  exit 1
fi

./scripts/backup_database.sh

find backups -type f -name 'glidecrm-*.tar.gz.enc' -mtime +14 -delete

if [[ -z "${BACKUP_RCLONE_DEST:-}" ]]; then
  echo "BACKUP_RCLONE_DEST is empty. The encrypted backup is only on this server."
  exit 0
fi

if ! command -v rclone >/dev/null 2>&1; then
  echo "rclone is not installed, so the off-server copy did not run." >&2
  exit 1
fi

rclone copy backups "${BACKUP_RCLONE_DEST}" --include 'glidecrm-*.tar.gz.enc'
rclone delete "${BACKUP_RCLONE_DEST}" --include 'glidecrm-*.tar.gz.enc' --min-age 14d
echo "Copied encrypted backups to ${BACKUP_RCLONE_DEST} and removed remote files older than 14 days."
