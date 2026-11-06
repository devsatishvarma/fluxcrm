# glidecrm

A self-hosted CRM for Infoshare Systems, designed for up to 50 users and
approximately 500,000 records without a platform rewrite.

## Project documents

- [Architecture and MVP specification](architecture-MVP-spec.md) — product,
  data, workflow, security, and operational baseline.
- [MVP delivery plan](docs/MVP_DELIVERY_PLAN.md) — phase-by-phase design,
  development, test, and release gates.
- [Development status](DEVELOPMENT_STATUS.md) — current phase, objective
  completion, blockers, evidence, and next actions.
- [Specification decisions and deviations](docs/SPEC_DECISIONS_AND_DEVIATIONS.md)
  — confirmed business settings and the required record of every deliberate
  change from the baseline.
- [Development guide](docs/DEVELOPMENT.md) — local startup, checks, browser
  smoke tests, and migrations.
- [Team setup (clone & run locally)](docs/TEAM_SETUP.md) — onboarding for
  teammates using Docker Compose or a pre-built image.
- [Operations guide](docs/OPERATIONS.md) — topology, health semantics,
  scheduler behavior, backup, and restore drills.

## Start locally

Create Docker volumes once (see [Team setup](docs/TEAM_SETUP.md) for full onboarding):

```bash
docker volume create fluxcrm_mysql_data
docker volume create fluxcrm_uploads
cp .env.example .env && docker compose up --build
```

Then open <http://127.0.0.1:8000>. Phase 0 foundation work is in progress; see
the development status for verified gate results.
