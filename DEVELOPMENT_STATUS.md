# FluxCRM Development Status

> Update this file at the end of every work session and whenever a gate,
> blocker, decision, scope, or verification result changes.

## Current position

- **MVP completion:** 20% (14 of 69 Phase 0–9 gate items verified)
- **Current phase:** Phase 2 — Leads and lead-linked Deals
- **Phase status:** Not started
- **Phase completion:** 0% (0 of 7 gate items verified)
- **Planning baseline:** Complete
- **Last updated:** 2026-10-11
- **Last verified result:** Phase 1 identity gates passed on a clean MySQL
  database, in pytest, and against the local server. Production email delivery
  is still undecided.

## Current phase gate — Phase 2

- [ ] CRUD, search, filtering, pagination, and soft delete work in the UI and API.
- [ ] A Deal cannot be orphaned or linked to an Account before Phase 5.
- [ ] Invalid owners, taxonomy keys, money, currency, and dates are rejected.
- [ ] Stale versions return a conflict without overwriting newer data.
- [ ] Direct URL and API attempts cannot cross owner scope.
- [ ] Displayed fixture values reconcile to database values.
- [ ] Representative lists avoid N+1 queries and meet the phase performance budget.

## Completed phase gate — Phase 1

- [x] Clean-database setup and a safe rerun both succeed.
- [x] Active users can authenticate; disabled users cannot.
- [x] Reset tokens expire, are single-use, and are absent from logs.
- [x] Non-admin users cannot change company or user administration settings.
- [x] Company values survive restart and render in `America/Los_Angeles`.
- [x] Login/reset throttles and secure-cookie behavior pass automated checks.
- [x] No default production credential exists.

## Phase summary

- **Phase 0 — Foundation:** 7/7, complete.
- **Phase 1 — Company and identity:** 7/7, complete.
- **Phase 2 — Leads and lead-linked Deals:** 0/7, not started.
- **Phase 3 — Workflow:** 0/7, waiting for Phase 2.
- **Phase 4 — Activities and tasks:** 0/6, waiting for Phase 3.
- **Phase 5 — Accounts, Contacts, conversion:** 0/7, waiting for Phase 4.
- **Phase 6 — Teams, RBAC, audit:** 0/7, waiting for Phase 5.
- **Phase 7 — Reports and dashboards:** 0/7, waiting for Phase 6.
- **Phase 8 — Import/export:** 0/8, waiting for Phase 7.
- **Phase 9 — Cloud pilot/hardening:** 0/6, waiting for Phase 8.
- **Phase 10 — Post-MVP modules:** separately approved; excluded from MVP %.

## Active blockers

None for starting Phase 2.

## Decisions needed later

- Before production password reset: select the email delivery provider and
  failure-alert owner. Development reset uses the console/locmem backend.
- Company logo upload is optional and was not supplied. It can be added later
  from company settings.
- Before Phase 9: select the cloud provider, managed MySQL offering, backup
  target, alert owners, and incident contacts.
- Before production pilot: approve data classification, retention/deletion,
  attachment, and antivirus policies.
- After the pilot: separately prioritize and approve Phase 10 modules and
  Microsoft 365 tenant/licensing policy.

## Next three actions

1. Freeze version 1 of the starter taxonomy before Lead or Deal migrations.
2. Define normalization, owner scope, optimistic locking, and soft delete for
   leads and lead-linked deals.
3. Implement Lead and lead-linked Deal models, screens, and API.

## Latest evidence

- 2026-10-11: Architecture specification reviewed against the phased plan.
- 2026-10-11: Business, access, tooling, deployment, and post-MVP decisions
  captured in the decision/deviation register.
- 2026-10-11: Verified all four README document targets exist; confirmed
  Phase 10 exclusion and the 69-item MVP gate total across planning artifacts;
  `git diff --check` passed.
- 2026-10-11: Locked 256 combined packages; Django 6.0.9, DRF 3.18.3, and
  `mysqlclient` 2.3.0 resolve alongside the preserved AI dependencies.
- 2026-10-11: Empty-MySQL migrations, Django system/migration-drift checks,
  Ruff checks, 6 pytest tests (82% focused foundation coverage), and one
  Playwright smoke test passed.
- 2026-10-11: Compose web, MySQL 8.4, and scheduler services became healthy;
  liveness returned 200 and readiness returned 503 while MySQL was stopped.
- 2026-10-11: Rebuilt the final image; web readiness and the single scheduler
  are healthy, and request logs contain JSON request IDs, status, and latency.
- 2026-10-11: Committed `13289eb` and `40a0734` and pushed them to
  `phase-0-foundation`. Direct push to `main` was blocked.
- 2026-10-11: Cloned `40a0734` to a clean directory. `cp .env.example .env &&
  docker compose up --build` produced healthy web, MySQL, and scheduler
  services; `/health/`, `/ready/`, and the home page passed. The checkout had
  no source changes. The existing named database volume was reused, so this
  run did not repeat the empty-database migration.
- 2026-10-11: The synthetic marker survived a full service restart.
- 2026-10-11: A compressed backup restored into a clean verification database;
  the fixture marker was reconciled before the verification database was
  removed.
- 2026-10-11: Secret-pattern scan, `uv lock --check`, `git diff --check`, and
  `docker compose config --quiet` passed.
- 2026-10-11: GitHub Actions run 38182395029 succeeded for `27e59d6` on
  `phase-0-foundation`. A clean MySQL 8.4 service applied every migration,
  including `core.0001_initial`. Ruff, Django checks, migration-drift checks,
  6 pytest tests, and 1 Playwright smoke test passed. An earlier run,
  38181980759, also succeeded.
- 2026-10-11: Ruff passed. Fourteen pytest tests passed on MySQL, covering
  setup rerun, active and disabled login, single-use expiring reset tokens,
  redacted reset paths, standard-user denial, Pacific time rendering, login
  and reset throttles, and secure cookies.
- 2026-10-11: Recreated the local `fluxcrm` database and applied the identity
  user migration. Live setup stored Infoshare Systems and the first
  administrator; repeating setup redirected to login. Home rendered
  `2026-10-11 17:31 America/Los_Angeles`. A standard user received 403 on
  company settings and user administration.
- 2026-10-11: Disabling that standard user left the next sign-in on the login
  page. After stopping and starting the app process, setup still redirected
  to login, the administrator could sign in, and home still showed Infoshare
  Systems Inc. at `2026-10-11 17:44 America/Los_Angeles`.
- 2026-10-11: Browser walk confirmed the setup form, then login was required
  for `/`, `/company/`, `/users/`, and a repeated `/setup/`. The browser
  password field was not submitted; the signed-in pages were checked on the
  same local server.

## Recent decision/change log

- **2026-10-11 — Planning baseline:** Adopted Design → Develop → Verify → Gate
  for every phase; no phase advances with failed CI or unresolved critical
  defects.
- **2026-10-11 — Progress calculation:** Phase and MVP percentages count only
  reproducibly passed gate items. Phase 10 is excluded.
- **2026-10-11 — Company configuration:** Confirmed Infoshare Systems values,
  USD, January fiscal year, and `America/Los_Angeles`.
- **2026-10-11 — Tooling:** Confirmed GitHub Actions, MySQL 8.4,
  pytest-django, Ruff, and Playwright.
- **2026-10-11 — Scope:** Cloud provider selection is deferred to Phase 9;
  Phase 10 modules require separate post-pilot approval.
- **2026-10-11 — Package identity:** Renamed the Python distribution from
  `agents` to `fluxcrm` with user approval; all existing dependencies remain.
- **2026-10-11 — Identity app:** Custom users live in `identity` so the
  swappable user is created in that app's first migration. `accounts` stays
  reserved for CRM customer records. See D-009 and D-010.

## How to maintain this file

1. Change only a gate item with repeatable evidence to `[x]`.
2. Recalculate the phase percentage from that phase's passed/total gate items.
3. Recalculate MVP percentage from all passed/69 Phase 0–9 gate items.
4. Keep only current blockers and three concrete next actions here.
5. Add a dated evidence line for commands, CI runs, walkthroughs, restore
   drills, performance measurements, or gate reviews.
6. Link any architecture/scope change to
   [`docs/SPEC_DECISIONS_AND_DEVIATIONS.md`](docs/SPEC_DECISIONS_AND_DEVIATIONS.md)
   before implementation.
