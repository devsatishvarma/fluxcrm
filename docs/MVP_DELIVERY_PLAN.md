# GlideCRM MVP Delivery Plan

## 1. Purpose

This is the execution plan for the architecture in
[`architecture-MVP-spec.md`](../architecture-MVP-spec.md). It covers design,
development, testing, release controls, and progress reporting for MVP Phases
0–9. Phase 10 is post-MVP and requires separate approval.

The original architecture remains the product baseline. Confirmed decisions and
all departures from it are recorded in
[`SPEC_DECISIONS_AND_DEVIATIONS.md`](SPEC_DECISIONS_AND_DEVIATIONS.md).
Current progress is recorded in
[`DEVELOPMENT_STATUS.md`](../DEVELOPMENT_STATUS.md).

## 2. Delivery rules

### 2.1 Phase lifecycle

Every phase follows the same lifecycle:

1. **Design:** confirm requirements, data changes, permissions, failure modes,
   observability, migration safety, and acceptance tests.
2. **Develop:** deliver the smallest end-to-end vertical slices. HTML/HTMX,
   REST API, jobs, and bulk paths call the same domain services.
3. **Verify:** run automated tests on MySQL 8.4, complete a human walkthrough,
   inspect logs/audit output, and exercise failure and rollback paths.
4. **Gate:** record evidence in `DEVELOPMENT_STATUS.md`. Do not begin the next
   phase until all gate items pass.

A phase cannot pass with failing CI, an unresolved critical defect, missing
negative authorization coverage, or an untested migration/rollback procedure.
Synthetic data is mandatory through the access-control and operational gates.

### 2.2 Architecture boundaries

- One Django 6 monolith split into `core`, `accounts`, `leads`, `sales`,
  `activities`, `imports`, `reporting`, and `audit` apps.
- MySQL 8.4/InnoDB is the acceptance database in development and CI. SQLite is
  not an acceptance substitute.
- Business actions are explicit transactional services reused by forms, DRF
  endpoints, HTMX actions, management commands, and scheduled jobs.
- Server-side scope and action authorization are applied before querying,
  aggregating, mutating, importing, or exporting records.
- The existing Python AI dependencies remain. Phase 0 adds and pins the CRM and
  test dependencies alongside them and proves that the combined lock resolves.
- No Redis, external task queue, separate SPA, or microservice is introduced
  before measured need and a recorded architecture decision.

### 2.3 Quality strategy

The standard toolchain is GitHub Actions, Ruff, pytest-django, Playwright, and a
MySQL 8.4 service. Each vertical slice includes:

- model constraints and validation tests;
- domain-service transaction, idempotency, and failure-injection tests;
- form, HTMX, serializer, and API behavior tests;
- positive and negative object/action/scope authorization tests;
- audit-event and sensitive-log-redaction assertions;
- Playwright smoke coverage for critical user journeys;
- migration forward/rollback checks where rollback is safe;
- query-count or representative performance checks where the phase adds lists,
  aggregates, imports, or large fixtures.

Regression coverage is required for every fixed defect. CI evidence and manual
walkthrough results are linked or summarized in the progress tracker.

## 3. Phase plan

## Phase 0 — Foundation

**Goal:** a reproducible, observable Django skeleton that starts against MySQL
and can be safely changed.

### Design

- Confirm package layout, settings modules, environment-variable contract, URL
  namespaces, and app boundaries.
- Define health versus readiness semantics, request-ID propagation, structured
  log schema, and secret/PII redaction rules.
- Define the migration workflow, fixture loading, backup artifact format, and
  clean-restore procedure.
- Define GitHub Actions jobs and protected quality checks.

### Develop

- Add pinned Django, DRF, MySQL, HTMX/template support, test, lint, and browser
  dependencies without removing the existing AI dependencies.
- Create the Django project and empty app boundaries.
- Add Docker Compose services for web, MySQL 8.4, and exactly one scheduler.
- Add `.env.example`, startup validation, health/readiness endpoints, request
  IDs, structured logging, and a minimal synthetic fixture command.
- Add GitHub Actions for Ruff, Django checks, clean-database migrations,
  pytest, and Playwright smoke tests.
- Document local startup, migration, backup, restore, and common failure
  recovery.

### Verify and gate

- A clean clone starts with one documented command.
- The same migrations apply to an empty local and CI MySQL database.
- An invalid/unavailable database produces a clear failed readiness result.
- Container restart preserves database and upload volumes.
- A database backup restores into a clean database and the restored app starts.
- No secret is committed or emitted in logs.
- The existing and new dependencies resolve together without an unreviewed
  conflict.

## Phase 1 — Company setup and identity

**Goal:** secure first-run setup and controlled internal user access.

### Design

- Finalize first-administrator bootstrap and repeat-run behavior.
- Define user invitation/create/disable/reset flows and email behavior. Select
  an email delivery provider before enabling production password reset.
- Map the confirmed company profile, USD, January fiscal start, and
  `America/Los_Angeles` defaults to validated fields.
- Define login/reset throttles, idle timeout, security audit events, and
  initial Admin/Standard User permissions.

### Develop

- Implement singleton company settings and protected logo upload.
- Implement the custom user profile, manager-ready schema, time zone, and
  initial roles.
- Add login, logout, expiring single-use reset, user administration, disabled
  account handling, CSRF protection, and secure-cookie settings.
- Add first-run setup, audit events, authentication logs, and tests.

### Verify and gate

- Clean-database setup and safe rerun both succeed.
- Active users can authenticate; disabled users cannot.
- Reset tokens expire, are single-use, and are absent from logs.
- Non-admin users cannot change company or user administration settings.
- Company values survive restart and render in the configured time zone.
- Login/reset throttles and secure-cookie behavior pass automated checks.
- No default production credential exists.

## Phase 2 — Leads and lead-linked Deals

**Goal:** usable, scoped lead and basic Deal management through UI and API.

### Design

- Freeze version 1 of the starter taxonomy before migrations or fixtures.
- Define normalization for email/domain, UUID/external ID generation, audit
  snapshots, optimistic-lock conflicts, soft delete, and owner scope.
- Trace each list filter and sort to an allow-listed indexed field.
- Keep Deals lead-linked in this phase; Account/Contact conversion remains out
  of scope until Phase 5.

### Develop

- Implement Lead and lead-linked Deal models with ownership, versioning,
  timestamps, audit fields, soft deletion, money/currency, and indexes.
- Implement CRUD, search, filters, pagination, empty/error states, and details
  using templates/HTMX and `/api/v1`.
- Enforce owner scope and page-size caps in shared query/policy services.
- Seed known-result synthetic leads and Deals.

### Verify and gate

- CRUD, search, filtering, pagination, and soft delete work in UI and API.
- A Deal cannot be orphaned or linked to an Account before Phase 5.
- Invalid owners, taxonomy keys, money, currency, and dates are rejected.
- Stale versions return a conflict without overwriting newer data.
- Direct URL and API attempts cannot cross owner scope.
- Displayed fixture values reconcile to database values.
- Representative lists avoid N+1 queries and meet the phase performance budget.

## Phase 3 — Lead and Deal workflow

**Goal:** explicit, auditable pipeline behavior shared by all interfaces.

### Design

- Encode the architecture's lead/deal transitions, stage gates, terminal
  outcomes, reopen rules, and required reasons.
- Define editable versus system-protected stage configuration and behavior when
  a stage is retired.
- Define the admin correction path and concurrency behavior.

### Develop

- Add lead/deal stage configuration and append-only stage history.
- Implement transactional transition/close/reopen services with field gates,
  probability snapshots, actor/time, reason, and duration.
- Add list/Kanban movement through the same transition service.
- Add manager probability override with mandatory reason and audit.

### Verify and gate

- Every allowed and rejected transition is covered at service, UI, and API
  layers.
- Drag/drop cannot bypass stage gates and explains missing fields.
- Terminal outcome reasons and Won amount/date requirements are enforced.
- Concurrent changes conflict rather than silently overwrite.
- History actor, timestamp, duration, reason, and probability are correct.
- Closed and held Deals are excluded from open pipeline totals.
- Admin correction is reversible where possible and always audited.

## Phase 4 — Activities and tasks

**Goal:** reliable follow-up workflows and a complete linked timeline.

### Design

- Define activity/task linking, quick-add defaults, reminder policy, stale
  rules, scheduler run keys, retry behavior, and time-zone boundaries.
- Confirm that MVP reminders are in-app/batched unless an email provider has
  been approved.

### Develop

- Implement Activity, ActivityLink, Task, and record links.
- Add quick logging, linked timelines, due/overdue/upcoming views,
  complete/snooze, and stale-record indicators.
- Implement idempotent `run_due_jobs` scheduling with one scheduler process,
  run records, retries, and health telemetry.

### Verify and gate

- One activity appears once on every linked record.
- Complete/snooze operations and audit events are consistent.
- Due times render correctly per user, including DST boundaries.
- Repeated scheduler runs do not duplicate reminders.
- Failed jobs retry safely; missed/repeated failures are observable.
- Quick-add defaults the source record and supports the documented keyboard
  interaction without interfering with form fields.

## Phase 5 — Accounts, Contacts, and lead conversion

**Goal:** introduce customer structures and safe, human-reviewed conversion.

### Design

- Define account/contact duplicate scoring and explainable match reasons.
- Define hierarchy cycle prevention, primary-contact concurrency, permitted
  conversion account types, explicit field-choice behavior, and conversion
  idempotency.
- Specify failure-injection points for the conversion transaction.

### Develop

- Implement Account and Contact, hierarchy, reports-to, primary contact, and
  duplicate candidates.
- Implement the conversion wizard: match/create Account, match/create Contact,
  transfer/create/skip Deal, review, then commit in one transaction.
- Re-parent open lead Deals while preserving history and source references.
- Preserve the converted Lead outside active queues.

### Verify and gate

- Account and contact/reporting hierarchies cannot cycle.
- At most one primary Contact exists per Account under concurrent requests.
- Exact/fuzzy candidates require an explicit human choice; no silent merge or
  overwrite occurs.
- Duplicate conversion submissions are idempotent.
- Injected failures leave no partial Account, Contact, Deal, or Lead state.
- Re-parented Deals retain values and history.
- Conversion permissions, source links, timeline note, and audit trail pass.

## Phase 6 — Teams, RBAC, and audit review

**Goal:** prove the complete role/scope model before broader reporting or data
movement.

### Design

- Translate the architecture matrix into versioned object/action/scope rules.
- Define recursive manager traversal, cycle handling, team interaction,
  privilege-change review, and denied-access telemetry.
- Build the positive/negative test matrix before enabling each grant.

### Develop

- Implement teams, manager tree, full roles, editable grants, and policy
  services.
- Apply scoped querysets and action checks to HTML, API, search, counts,
  aggregates, bulk actions, and preparatory import/export paths.
- Add immutable audit search with record-scope filtering.

### Verify and gate

- Every matrix cell has positive and negative tests.
- Managers see recursive descendants and no unrelated branch.
- Read-only users cannot mutate through forms, HTMX, API, or crafted requests.
- Export remains separately permissioned.
- Privilege changes and denials are logged without exposing CRM content.
- Audit rows cannot be created, updated, or deleted through user-facing paths.
- Active administrator membership is manually reviewed.

## Phase 7 — Reports and dashboards

**Goal:** explainable, scoped metrics that reconcile to source data.

### Design

- Write a fixture equation and expected result for every report before its
  query is implemented.
- Define user-local date boundaries, fiscal periods, cohort rules, parent
  rollups, closed/open semantics, and temporary export lifetime.
- Set initial query budgets from representative seeded data.

### Develop

- Implement Rep, Manager, and Executive dashboards incrementally.
- Add specified pipeline, forecast, conversion, activity, aging, velocity, and
  won/lost reports with accessible data tables beneath Chart.js views.
- Reuse source-record scope in every aggregate and export.
- Add slow-query/report telemetry and guarded report exports.

### Verify and gate

- Every total reconciles to hand-checked fixtures.
- Parent rollups do not double-count descendants.
- Cohort, fiscal-quarter, prior-period, and time-zone boundaries are correct.
- Raw rows and aggregates expose no records beyond viewer scope.
- Large detail results remain paginated.
- Report duration/query count meet measured budgets.
- Export audit includes actor, filters, fields, and row count.

## Phase 8 — Import and export

**Goal:** safe, explainable bulk data movement with recovery.

### Design

- Deliver CSV first; begin XLSX only after CSV acceptance passes.
- Define field maps, natural keys, deterministic duplicate policies, chunk
  size, idempotency key, staging retention, rollback conflicts, and limits.
- Threat-model malicious files and spreadsheet formula injection.

### Develop

- Add template download, private upload staging, mapping, validation preview,
  reusable mappings, and row-level errors.
- Add idempotent chunked commit, batch/row history, downloadable results, and
  compensating rollback.
- Add XLSX parsing without formula execution after the CSV gate.
- Add filtered/selected asynchronous exports with expiring private downloads.

### Verify and gate

- Preview produces no business-record side effects.
- Invalid rows are isolated and explained.
- Retry/replay does not duplicate committed rows.
- Duplicate policies yield deterministic results.
- Rollback preserves audit and flags records changed after import.
- Formula cells are rejected on import and dangerous export prefixes escaped.
- File/MIME/size/row limits and all permission scopes are enforced.
- A 50,000-row representative batch completes within a recorded operational
  budget without a request-long transaction.

## Phase 9 — Cloud pilot and operational hardening

**Goal:** a measured, recoverable pilot ready for controlled real use.

### Design

- Select and record the provider, managed MySQL offering, networking, secret
  store, backup target, alert owners, release rollback, and incident contacts.
- Define pilot users, data classification/retention/deletion, attachment
  policy, performance workload, and success criteria.

### Develop

- Deploy the same image/schema behind HTTPS with private MySQL networking and
  protected secrets.
- Add offsite encrypted backups, monitoring, actionable alerts, runbooks, and
  deployment/migration automation.
- Generate production-like synthetic data up to 500,000 total records and a
  50-user workload scenario.

### Verify and gate

- `check --deploy`, TLS, host/origin, cookie, proxy, and network controls pass.
- A current database-and-upload backup restores into a clean environment.
- Backup age, restore result, app/DB health, storage, latency, errors, and jobs
  have named actionable alerts.
- Normal filtered lists meet the <2 second target on agreed pilot hardware, or
  a measured remediation decision is recorded.
- The 50-user scenario and permission matrix pass with representative data.
- A small pilot completes with no unresolved critical defect and reviewed
  telemetry/user feedback.

## Phase 10 — Post-MVP modules

Phase 10 is not one implementation batch. Entra SSO, Outlook calendar,
OneDrive, goals/scorecards, sales handbook, cases, product/price books/lines,
and any new integration each require a separate approved design, permission
model, migration/rollback plan, feature-isolation strategy, and pilot. Microsoft
licensing, tenant policy, app registration, consent, and minimum OAuth scopes
must be confirmed before planning those integrations.

## 4. Cross-phase requirement gates

### Security and privacy

- Use server-side authorization on every path; hidden controls are not a
  security boundary.
- Keep passwords, tokens, sessions, secrets, and unnecessary CRM content out
  of logs and audit snapshots.
- Keep uploads private, non-executable, size/type checked, and outside the web
  root.
- Review authentication and access control against relevant OWASP ASVS
  controls before the pilot.

### Data and migrations

- Use UUID primary keys, immutable external IDs, UTC storage, decimal money,
  soft deletion, audit fields, and optimistic versions as specified.
- Review migration locks, data volume, backup state, forward recovery, and
  rollback feasibility before release.
- Never use production customer data until Phase 6 access controls and Phase 9
  restore/security gates pass.

### Observability and operations

- Preserve request IDs across web requests and jobs.
- Track request latency/errors, DB health, scheduler outcomes, storage,
  imports/exports, backup age, and restore evidence as each becomes relevant.
- Alerts require a named owner and action. Expected validation failures are not
  paged as incidents.

## 5. Progress calculation and maintenance

- Each Phase 0–9 percentage is `passed gate items / total gate items`, rounded
  to the nearest whole percent.
- Overall MVP percentage is `all passed gate items in Phases 0–9 / all gate
  items in Phases 0–9`, so phases with more acceptance work contribute more.
- Phase 10 is reported separately and never inflates MVP completion.
- Only reproducibly verified items count as passed. Partial implementation does
  not count unless the checklist item itself defines an independently
  verifiable increment.
- Update `DEVELOPMENT_STATUS.md` at the end of every work session and whenever
  a gate, blocker, scope, decision, or verification result changes.
- Record architecture or scope changes in
  `SPEC_DECISIONS_AND_DEVIATIONS.md` before implementing them.
