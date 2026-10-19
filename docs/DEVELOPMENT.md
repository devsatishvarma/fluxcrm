# Development Guide

## Prerequisites

- Docker Engine/Desktop with Compose
- `uv` 0.12.5 or compatible
- Python 3.12 for host-side tooling
- MySQL client headers and `pkg-config` for host-side `mysqlclient` builds
  (`brew install mysql-client pkg-config` on macOS)

## One-command clean start

From a clean checkout:

```bash
cp .env.example .env && docker compose up --build
```

Open <http://127.0.0.1:8000>. Readiness is available at
<http://127.0.0.1:8000/ready/>. Stop the stack with:

```bash
docker compose down
```

Named volumes intentionally preserve MySQL, uploads, and collected static files.
Never use `docker compose down --volumes` unless destroying local data is
explicitly intended.

## Host-side setup

The application always uses MySQL; SQLite is not supported as an acceptance
database.

```bash
export PKG_CONFIG_PATH="$(brew --prefix mysql-client)/lib/pkgconfig" # macOS
uv sync --frozen
cp .env.example .env
docker compose up -d database
export DJANGO_DEBUG=true
export DJANGO_SECRET_KEY=development-only-replace-before-deployment
export MYSQL_DATABASE=glidecrm
export MYSQL_USER=glidecrm
export MYSQL_PASSWORD=development-only-database-password
export MYSQL_HOST=127.0.0.1
uv run python manage.py migrate
uv run python manage.py seed_synthetic_data
uv run python manage.py runserver
```

When running on the host, set `MYSQL_HOST=127.0.0.1` (the example file already
uses the settings default). Inside Compose, the service overrides it to
`database`.

## Quality checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
MYSQL_USER=root MYSQL_PASSWORD=development-only-root-password \
  uv run pytest --cov=. --cov-report=term-missing
```

The elevated MySQL account is used only so Django can create and destroy an
isolated `test_glidecrm` database. Runtime commands use the restricted
`glidecrm` account.

Browser smoke tests require Chromium and a running application:

```bash
uv run playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8000 \
  uv run pytest -o addopts="" -m browser tests/browser
```

GitHub Actions runs the same checks against a clean MySQL 8.4 service.

## Migrations

1. Create migrations with `uv run python manage.py makemigrations`.
2. Review generated SQL and lock impact with
   `uv run python manage.py sqlmigrate APP MIGRATION`.
3. Test from an empty MySQL database and from a representative prior schema.
4. Document backup, forward recovery, and rollback limits before release.
5. Run `uv run python manage.py makemigrations --check --dry-run` before commit.

## Environment safety

- `.env` is ignored and must never be committed.
- `.env.example` contains local-only placeholders, not usable production
  secrets.
- Production startup fails if `DJANGO_SECRET_KEY` is absent.
- Set trusted proxy headers only behind a proxy that overwrites the forwarded
  protocol header.
- Logs are JSON and include request IDs. Do not add request bodies, credentials,
  tokens, cookies, or unnecessary CRM content to log extras.
