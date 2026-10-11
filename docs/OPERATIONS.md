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

## Database backup

Start the database, then run:

```bash
./scripts/backup_database.sh
```

The script uses a transaction-consistent dump, writes a private gzip file under
the ignored `backups/` directory, and validates the gzip stream. Copy approved
production backups to encrypted off-host storage; a local file alone is not a
complete backup.

## Restore drill

Restores are destructive. Use a clean disposable environment whenever testing:

```bash
RESTORE_CONFIRM=fluxcrm \
  ./scripts/restore_database.sh backups/fluxcrm-TIMESTAMP.sql.gz
uv run python manage.py migrate --check
curl --fail http://127.0.0.1:8000/ready/
```

Record the source backup, target, start/end time, result, and validation query
in `DEVELOPMENT_STATUS.md`. A backup is not proven until this drill succeeds.

Uploads must be backed up and restored with the database in production. The
Phase 9 provider decision will define encrypted off-host upload backup tooling;
Phase 0 does not claim that operational gate.

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

`check --deploy` warnings caused by intentionally disabled local HTTPS controls
are expected only in local development; they must be resolved for Phase 9.
