# Phase 0 Operations

## Service topology

- `web`: Django/Gunicorn; applies migrations before accepting traffic.
- `database`: MySQL 8.4/InnoDB using `utf8mb4_0900_ai_ci`.
- `scheduler`: one process invokes the idempotent due-job command each minute
  after web readiness succeeds.

MySQL, uploads, and static output use named volumes. The database port and web
port bind to loopback by default.

## Health semantics

- `/health/` is liveness only and does not query dependencies.
- `/ready/` executes `SELECT 1`; it returns HTTP 503 and a generic response when
  MySQL is unavailable.
- Every response includes `X-Request-ID`. A safe incoming ID is preserved;
  malformed IDs are replaced.

## Database and upload backup

Start the web and database containers, then run:

```bash
BACKUP_PASSPHRASE='replace-with-a-long-secret' ./scripts/backup_database.sh
```

The script writes a transaction-consistent database dump and a copy of the
upload volume into one archive under the ignored `backups/` directory. When
`BACKUP_PASSPHRASE` is set, the archive is encrypted with AES-256-CBC and the
unencrypted file is removed. Set that passphrase before the file is copied off
this machine. Keep 14 daily copies and 12 monthly copies. The off-host target
is still unnamed; a file that stays on this computer is not the off-host copy.

## Restore drill

Restoring into the application database replaces its data and, for a bundle,
replaces the upload volume. Prove a backup on an empty database first:

```bash
RESTORE_CONFIRM=glidecrm RESTORE_DATABASE=glidecrm_restore_drill RESTORE_UPLOADS=0 \
  BACKUP_PASSPHRASE='the-same-secret' \
  ./scripts/restore_database.sh backups/glidecrm-TIMESTAMP.tar.gz.enc
```

Then confirm `django_migrations` has rows in that database, drop the drill
database, and delete the drill archive. A restore of the application database
uses the same command without `RESTORE_DATABASE`. Record the source backup,
target, start and end time, and result in `DEVELOPMENT_STATUS.md`.

## Release rollback

Before changing the running image or applying a migration:

1. Take an encrypted backup with `./scripts/backup_database.sh`.
2. Record the current image id: `docker image inspect glidecrm-web --format '{{.Id}}'`.

To roll a release back:

1. `docker compose stop web scheduler`
2. Restore that pre-release backup into the application database. Include
   uploads. Do not run a reverse migration; the backup is the previous schema.
3. Start the recorded image, then `docker compose up -d web scheduler`.
4. Confirm `http://127.0.0.1:8000/ready/` returns 200.

## Alerts

The company administrator (Satish) owns every alert below until a second
incident contact is named. Each item names the check and the action. Expected
form-validation errors are not incidents.

| Signal | Action |
|---|---|
| `/ready/` is not 200 for two minutes | Read the web log for that request id. Restart web if the process died. If readiness stays down, check that MySQL is healthy. |
| `/health/` is 200 and `/ready/` is 503 | MySQL is the failed dependency. Restore service before users retry writes. |
| Newest backup is older than 26 hours | Run the backup command. If it fails, free disk space and run it again. Do not deploy. |
| Restore drill fails | Do not deploy. Keep the failed archive and fix the backup before the next release. |
| Scheduler job fails twice | Read the job row, fix the cause, and let the next minute run. Do not start a second scheduler. |
| Database volume or disk is nearly full | Expand the volume, then confirm `/ready/` and a new backup. |
| Error rate jumps just after a release | Roll back with the pre-release backup and the previous image. |

A paging service is not connected yet. Until it is, the administrator runs
these checks before a release and after a failed `/ready/`.

## Scheduler behavior

`python manage.py run_due_jobs` creates a unique `(name, run_key)` row for the
current UTC minute. A duplicate invocation skips work. Phase 4 will register
reminder and stale-record handlers behind this boundary.

Check recent outcomes through the database/admin and alert on missed runs or
repeated failures once production monitoring is configured.

## Failure checks

- Stop MySQL and confirm `/health/` remains 200 while `/ready/` becomes 503.
- Confirm readiness logs identify the failure without credentials or connection
  strings.
- Restart the stack and confirm data created before restart still exists.
- Do not enable HSTS until HTTPS is working on the final host.

## Release checklist

```bash
uv run python manage.py check
uv run python manage.py check --deploy
uv run python manage.py makemigrations --check --dry-run
uv run pytest
docker compose config --quiet
```

Local development keeps HTTPS redirects and HSTS off, so `check --deploy` warns
here. The release profile in `.env.example` is what must pass before a host
serves the app. Turn HSTS on only after HTTPS works on that host.
