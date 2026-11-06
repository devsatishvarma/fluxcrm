# Team setup: clone and run GlideCRM locally

Use this guide when onboarding a developer onto the **fluxcrm** GitHub repository. The app is a Django stack with MySQL; the supported local path is **Docker Compose** (recommended) or host-side Python with `uv` (see [Development guide](DEVELOPMENT.md)).

## Prerequisites

- **Git** and **GitHub access** to `https://github.com/devsatishvarma/fluxcrm` (or your org fork after you transfer access).
- **Docker Desktop** or **Docker Engine** with Compose v2 (`docker compose`).
- Optional for host-only runs: **Python 3.12**, **`uv`**, and on macOS **Homebrew** packages for MySQL client dev headers (see [DEVELOPMENT.md](DEVELOPMENT.md)).

## 1. Get the code

```bash
git clone https://github.com/devsatishvarma/fluxcrm.git
cd fluxcrm
git checkout main
git pull
```

Use SSH instead of HTTPS if your team standardizes on deploy keys or SSH auth:

```bash
git clone git@github.com:devsatishvarma/fluxcrm.git
```

## 2. Environment file

```bash
cp .env.example .env
```

Edit `.env` only if you need different ports or secrets; the example values are for **local development only**. Never commit `.env` (it is gitignored).

## 3. Docker volumes (first-time only)

Compose declares **named external volumes** for MySQL data and uploads. Create them once per machine before the first `docker compose up`:

```bash
docker volume create fluxcrm_mysql_data
docker volume create fluxcrm_uploads
```

If these are missing, Compose will error when starting the stack.

## 4. Run with Docker Compose (recommended)

Build and start the web app, database, and scheduler:

```bash
docker compose up --build
```

- **App:** [http://127.0.0.1:8000](http://127.0.0.1:8000) (port configurable via `WEB_PORT` in `.env`)
- **Readiness:** [http://127.0.0.1:8000/ready/](http://127.0.0.1:8000/ready/)

Stop the stack (keeps database and upload data in the named volumes):

```bash
docker compose down
```

To **reset local data** intentionally (destructive): remove the containers and the external volumes, then recreate the volumes and run `docker compose up --build` again.

## 5. Pre-built Docker image (optional)

The repo includes a **Dockerfile** at the repository root; Compose **builds** that image by default. If your team publishes a pre-built image to a registry (for example GitHub Container Registry or Docker Hub), you can run that image instead of building locally: point the Compose `web` (and `scheduler`) service at `image: <registry>/<name>:<tag>` with the same environment and volume mounts as in `compose.yaml`, or use `docker run` with equivalent flags, linked MySQL, and the same `.env` variables. Use the tag your team documents for each release.

## 6. Optional: run on the host (no app container)

For debugging with breakpoints on the host, see the **Host-side setup** section in [DEVELOPMENT.md](DEVELOPMENT.md) (starts the DB in Compose, runs Django with `uv run` on your machine).

## 7. Baseline / releases

Stable return points are marked with **git tags** (for example `phase-9-baseline`) and the **baseline branch** `baseline/phase-9` described in [DEVELOPMENT_STATUS.md](../DEVELOPMENT_STATUS.md). To sync to a specific baseline:

```bash
git fetch --tags
git checkout <tag-or-branch-name>
```

## Troubleshooting

- **Compose fails on volumes:** Ensure `fluxcrm_mysql_data` and `fluxcrm_uploads` exist (`docker volume ls`).
- **Port already in use:** Change `WEB_PORT` or `MYSQL_EXPOSE_PORT` in `.env`.
- **Deeper ops** (backup, scheduler, health checks): see [OPERATIONS.md](OPERATIONS.md).
