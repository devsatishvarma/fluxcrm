The run instructions are in `docs/DEVELOPMENT.md`. `README.md` has the same one-line start. `docs/OPERATIONS.md` covers health checks, backup, and restore, not how to launch the app.

GlideCRM is one Django application. There is no separate frontend or backend process. The pages are served by Django. Docker Compose runs three services: `web` (the app), `database` (MySQL), and `scheduler` (due jobs once a minute).

From the project directory:

```bash
cp .env.example .env && docker compose up --build
```

Then open http://127.0.0.1:8000. Readiness is http://127.0.0.1:8000/ready/. Stop it with `docker compose down`.

To run the app on your machine and keep only MySQL in Docker, `docs/DEVELOPMENT.md` has the host-side steps: `docker compose up -d database`, then `uv run python manage.py migrate` and `uv run python manage.py runserver`.