# FluxCRM Development Status

> Update this file at the end of every work session and whenever a gate,
> blocker, decision, scope, or verification result changes.

## Current position

- **MVP completion:** 7% (5 of 69 Phase 0–9 gate items verified)
- **Current phase:** Phase 0 — Foundation
- **Phase status:** In progress
- **Phase completion:** 71% (5 of 7 gate items verified)
- **Planning baseline:** Complete
- **Last updated:** 2026-10-11
- **Last verified result:** MySQL tests (6), Playwright smoke test (1), Compose
  health, failure behavior, restart persistence, and clean restore passed on
  2026-10-11.

## Current phase gate — Phase 0

- [ ] Clean clone starts with one documented command.
- [ ] Migrations pass against empty local and CI MySQL 8.4 databases.
- [x] Database failure produces a clear failed readiness result.
- [x] Container restart preserves database and upload volumes.
- [x] A backup restores successfully into a clean database.
- [x] No secrets are committed or emitted in logs.
- [x] Existing AI and new CRM dependencies resolve without unreviewed conflict.

## Phase summary

- **Phase 0 — Foundation:** 5/7, in progress.
- **Phase 1 — Company and identity:** 0/7, waiting for Phase 0.
- **Phase 2 — Leads and lead-linked Deals:** 0/7, waiting for Phase 1.
- **Phase 3 — Workflow:** 0/7, waiting for Phase 2.
- **Phase 4 — Activities and tasks:** 0/6, waiting for Phase 3.
- **Phase 5 — Accounts, Contacts, conversion:** 0/7, waiting for Phase 4.
- **Phase 6 — Teams, RBAC, audit:** 0/7, waiting for Phase 5.
- **Phase 7 — Reports and dashboards:** 0/7, waiting for Phase 6.
- **Phase 8 — Import/export:** 0/8, waiting for Phase 7.
- **Phase 9 — Cloud pilot/hardening:** 0/6, waiting for Phase 8.
- **Phase 10 — Post-MVP modules:** separately approved; excluded from MVP %.

## Active blockers

- The clean-checkout and CI migration gates require these uncommitted
  foundation files to be committed and the GitHub Actions workflow to run.

## Decisions needed later

- Before Phase 1 production reset: select the email delivery provider and
  failure-alert owner.
- Before Phase 1 completion: provide and approve the company logo, if one is to
  be included.
- Before Phase 9: select the cloud provider, managed MySQL offering, backup
  target, alert owners, and incident contacts.
- Before production pilot: approve data classification, retention/deletion,
  attachment, and antivirus policies.
- After the pilot: separately prioritize and approve Phase 10 modules and
  Microsoft 365 tenant/licensing policy.

## Next three actions

1. Review and commit the Phase 0 foundation files.
2. Run the GitHub Actions workflow and record the clean-MySQL migration,
   pytest, Ruff, and Playwright results.
3. Verify startup from a clean checkout, close the remaining two Phase 0 gates,
   and begin Phase 1 design.

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
- 2026-10-11: The synthetic marker survived a full service restart.
- 2026-10-11: A compressed backup restored into a clean verification database;
  the fixture marker was reconciled before the verification database was
  removed.
- 2026-10-11: Secret-pattern scan, `uv lock --check`, `git diff --check`, and
  `docker compose config --quiet` passed.

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
