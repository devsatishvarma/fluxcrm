# FluxCRM Development Status

> Update this file at the end of every work session and whenever a gate,
> blocker, decision, scope, or verification result changes.

## Current position

- **MVP completion:** 59% (41 of 69 Phase 0–9 gate items verified)
- **Current phase:** Phase 6 — Teams, RBAC, and audit review
- **Phase status:** Not started
- **Phase completion:** 0% (0 of 7 gate items verified)
- **Planning baseline:** Complete
- **Code baseline:** Tag `pre-phase-5`. Phase 5 is implemented and verified locally, and is not committed yet.
- **Last updated:** 2026-10-11
- **Last verified result:** Phase 5 passed 54 MySQL tests, system checks, and migration-drift checks. The Django test client exercised account creation, duplicate confirmation, and conversion.

## Current phase gate — Phase 6

- [ ] Every permission-matrix cell has positive and negative tests.
- [ ] Managers see recursive descendants and no unrelated branch.
- [ ] Read-only users cannot mutate through forms, HTMX, API, or crafted requests.
- [ ] Export remains separately permissioned.
- [ ] Privilege changes and denials are logged without exposing CRM content.
- [ ] Audit rows cannot be created, updated, or deleted through user-facing paths.
- [ ] Active administrator membership is manually reviewed.

## Completed phase gate — Phase 5

- [x] Account and contact reporting hierarchies cannot cycle.
- [x] At most one primary Contact exists per Account under concurrent requests.
- [x] Exact and fuzzy duplicate candidates require an explicit human choice.
- [x] Duplicate conversion submissions are idempotent.
- [x] Injected failures leave no partial Account, Contact, Deal, or Lead state.
- [x] Re-parented Deals retain values and history.
- [x] Conversion permissions, source links, timeline note, and audit trail pass.

## Completed phase gate — Phase 4

- [x] One activity appears once on every linked record.
- [x] Complete and snooze operations and their audit events stay consistent.
- [x] Due times render correctly per user, including DST boundaries.
- [x] Repeated scheduler runs do not duplicate reminders.
- [x] Failed jobs retry safely, and missed or repeated failures are observable.
- [x] Quick-add defaults the source record and keeps the documented keyboard
      interaction from interfering with form fields.

## Completed phase gate — Phase 3

- [x] Every allowed and rejected transition is covered at the service, UI, and API.
- [x] Drag and drop cannot bypass stage gates and explains missing fields.
- [x] Terminal outcome reasons and Won amount and close date are enforced.
- [x] Concurrent changes conflict instead of overwriting newer data.
- [x] History records actor, time, duration, reason, and probability.
- [x] Closed and held Deals are excluded from open pipeline totals.
- [x] Admin correction is reversible where possible and always audited.

## Completed phase gate — Phase 2

- [x] CRUD, search, filtering, pagination, and soft delete work in the UI and API.
- [x] A Deal cannot be orphaned or linked to an Account before Phase 5.
- [x] Invalid owners, taxonomy keys, money, currency, and dates are rejected.
- [x] Stale versions return a conflict without overwriting newer data.
- [x] Direct URL and API attempts cannot cross owner scope.
- [x] Displayed fixture values reconcile to database values.
- [x] Representative Lead and Deal lists avoid N+1 queries; the accepted
      500,000-row timing measurement remains in Phase 9.

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
- **Phase 2 — Leads and lead-linked Deals:** 7/7, complete. List queries stayed
  flat. The 500,000-row clock is a Phase 9 measurement, accepted on 2026-10-11.
- **Phase 3 — Workflow:** 7/7, complete. Graphs, history, Kanban, close rules,
  and admin correction share one transition service. See D-012.
- **Phase 4 — Activities and tasks:** 6/6, complete. Linked timelines,
  in-app reminders, and stale badges. See D-013.
- **Phase 5 — Accounts, Contacts, conversion:** 7/7, complete. Hierarchies,
  one primary contact, explicit duplicate choice, and one conversion
  transaction. See D-016.
- **Phase 6 — Teams, RBAC, audit:** 0/7, not started.
- **Phase 7 — Reports and dashboards:** 0/7, waiting for Phase 6.
- **Phase 8 — Import/export:** 0/8, waiting for Phase 7.
- **Phase 9 — Cloud pilot/hardening:** 0/6, waiting for Phase 8.
- **Phase 10 — Post-MVP modules:** separately approved; excluded from MVP %.

## Active blockers

None for starting Phase 6. Stage moves still use the Phase 3 reason-based
gates; requiring a logged activity before a stage change is a later decision.
See D-013. Manager-tree visibility starts in Phase 6.

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

1. Define the role matrix, recursive manager traversal, and denied-access logging.
2. Implement teams, manager scope, and editable grants on the existing record pages.
3. Cover every permission-matrix cell with positive and negative tests.

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
- 2026-10-11: Nineteen pytest tests passed on MySQL, including the new lead
  and deal coverage. UI and API create, search, filter, paginate, and soft-delete
  records. A deal without a lead is rejected, as is an Account link. Invalid
  stage, type, amount, currency, date, and owner values return 422. A stale
  version returns 409 and leaves the stored company name unchanged. Another
  owner's direct URL and API read return 403, and that user's list count is 0.
- 2026-10-11: Seeded `lead-1002` and `deal-2002` match the database and the
  signed-in pages: Northstar Robotics and 12500.00. An empty search says no
  leads match. Adding three leads did not increase the list query count.
  Create logs and audit snapshots omit the lead email and notes.
- 2026-10-11: The local server required login for `/leads/`. After signing in,
  `/leads/` showed Northstar Robotics and Pinecone Health Group, the empty
  filter showed its empty state, and `/deals/` showed the Northstar renewal
  at 12500.00.
- 2026-10-11: The user accepted leaving the 500,000-row list timing for Phase 9.
  Phase 2's list gate is complete on the flat query-count evidence.
- 2026-10-11: Ruff, Django system check, and migration-drift check passed.
  MySQL pytest covered every lead and deal graph pair in the transition
  service, plus UI and API allowed and rejected moves, drag posts that leave
  the stage unchanged and name the missing field, won amount and close date,
  loss and hold reasons, stale-version 409, history actor/duration/reason/
  probability, an open-pipeline total of 100.00 that excludes won, lost, and
  held deals, reversible audited admin correction, admin-only unqualified
  reopen, retired targets, and admin-only probability override.
- 2026-10-11: Applied `core.0003_phase3_workflow` and `sales.0002_phase3_workflow`
  to the local database. `identity.0002_alter_user_manager` aligns the manager
  foreign key with Django's swappable-user migration state. Twenty-four pytest
  tests passed.
- 2026-10-11: Signed-in local check: a new lead rejected `SQL_READY` with the
  stage unchanged, then moved to `CONTACTED` and showed that reason in history.
  A $50 deal raised the open pipeline from 60500.00 to 60550.00; closing it
  lost without a reason returned 422, and closing it with a price reason
  returned the total to 60500.00 and removed it from the board. Both
  verification records were deleted. Unsigned browser requests to `/leads/board/`
  and `/deals/board/` redirected to login.
- 2026-10-11: Audited Phases 1–3 against the architecture, delivery plan,
  decision register, implementation, and gates. Removed the documented local
  credential, separated FluxCRM Admin from Django superuser/staff, removed the
  Django admin route, made setup races safe, added audited invitation and
  reset actions, and validated logo signatures. Twelve identity tests passed.
- 2026-10-11: Phase 2 hardening added complete Deal UI coverage, negative
  cross-owner read/write tests, Deal stale-version coverage, owner/date/type/
  temperature list filters, indexed `updated_at` ordering, and flat query-count
  checks for both Lead and Deal lists. Seven pipeline tests passed. The
  500,000-row wall-clock measurement remains an explicitly accepted Phase 9
  gate.
- 2026-10-11: Interactive records now start at `NEW`; fixture stages use
  audited corrections. Every Lead and Deal graph pair passed through the
  service, HTML, and API layers. Deal corrections clear stale terminal state,
  probability override reasons persist, and StageHistory rejects update and
  delete. Nine workflow tests passed.
- 2026-10-11: The complete MySQL suite passed with 34 tests. Ruff, Django
  system checks, migration-drift checks, and local migrations passed. Live
  sign-in and the Lead list, Deal list, and both boards returned 200; `/admin/`
  returned 404. The existing administrator is no longer staff/superuser, and
  migrations added baseline history for five Leads and two Deals. The
  Playwright foundation/browser smoke also passed.
- 2026-10-11: Phase 4 MySQL suite passed with 41 tests. One activity linked to
  a Lead and a Deal renders once on each timeline. Complete and snooze stay
  consistent with their audit events. July, November, and March due times
  render in `America/Los_Angeles`, including the DST boundaries. A repeated
  scheduler run in the same minute creates one reminder; a failed run stays
  `FAILED` and the next minute delivers that reminder once. Quick-add posts
  the current record, defaults to Call, and the `A` shortcut ignores form
  fields. Lead and Deal lists show stale badges. Unsigned `/tasks/` redirects
  to login. Local seed created `act-3001`, `act-3003`, and `task-4001`.
- 2026-10-11: Lead and deal pages show age from the created date and time in the
  current stage. Stage history now says “Started in PROPOSAL” instead of
  “to PROPOSAL by after 0 seconds” and hides the internal baseline label.
  Leads have a Lead rating of Hot, Warm, or Cold. Deals have Deal confidence
  of High, Medium, or Low. Tasks can be added from a lead, a deal, or
  the task list. 45 MySQL tests passed. See D-014.
- 2026-10-11: Phase 5 passed 54 MySQL tests. Ruff, Django checks, and
  migration-drift checks passed. Account and contact cycles are rejected, one
  primary contact survives concurrent updates, duplicate matches require a
  choice, a second conversion returns the first result, and an injected
  failure leaves no account, contact, or deal change. Open deals keep their
  amount, stage, and history when moved to the account. The convert page
  returns 422 until the new account is confirmed, then creates it.
- 2026-10-11: Lead and deal stages change independently. Closed Won and Closed
  Lost convert the source lead without changing the lead stage. An exact
  company match receives the lead as a contact; a similar name gets a new
  account. Closed Hold does not convert. See D-017.

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
- **2026-10-11 — Lead-linked deals:** Phase 2 deals require a lead and do not
  link to an Account yet. See D-011.
- **2026-10-11 — List timing:** The 500,000-row list measurement stays in
  Phase 9. The user accepted that because that volume is not expected soon.
- **2026-10-11 — Protected stages:** Lead and deal graphs are system-protected.
  Activity, task, and primary-contact gates stay in Phases 4 and 5. Admin is
  the correction and probability-override role until Phase 6. See D-012.
- **2026-10-11 — Identity administration:** FluxCRM Admin is an audited
  application role, not Django staff/superuser access. Invitations and
  administrator-requested resets use the configured email backend. See D-009
  and D-010.
- **2026-10-11 — Follow-ups:** Activities and tasks are linked records with
  in-app reminders. Email reminders stay deferred. Sample rows that require
  account deal `deal-2001` are not seeded. See D-013.
- **2026-10-11 — Phase 4 baseline:** Phases 0–4 are the checkpoint at tag
  `pre-phase-5`.
- **2026-10-11 — Accounts and conversion:** A deal belongs to one lead or one
  account. Conversion keeps the lead, requires an explicit duplicate choice,
  and moves only open deals. See D-016.

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
