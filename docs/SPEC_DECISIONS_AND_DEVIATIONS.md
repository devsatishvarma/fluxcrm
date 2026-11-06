# GlideCRM Specification Decisions and Deviations

## Purpose

[`architecture-MVP-spec.md`](../architecture-MVP-spec.md) is the architecture
baseline. This register records confirmations, clarifications, and deliberate
departures so that implementation never silently changes the product.

For future entries, include the date, status, decision, rationale, affected
phases, specification impact, and approval source. Record a proposed change
here before implementing it.

## Confirmed decisions

### D-001 — Company profile

- **Date/status:** 2026-10-11 — Confirmed
- **Legal name:** Infoshare Systems Inc.
- **Display name:** Infoshare Systems
- **Address:** 26040 Acero, Mission Viejo, CA 92691, United States
- **Industry:** Information Technology
- **Offered services:** IT Consulting; Professional Services; Managed Services;
  Value Added Reseller
- **Logo:** Not yet supplied; required only if the initial production profile
  must display one.
- **Affected phase:** 1
- **Specification impact:** Replaces the synthetic Example Consulting company
  seed for the initial configured company. Synthetic customer/lead data remains
  required during development.
- **Approval source:** User-provided values.

### D-002 — Financial calendar and time zone

- **Date/status:** 2026-10-11 — Confirmed
- **Base/reporting currency:** USD (`$`)
- **MVP currency behavior:** Deals retain the ISO `USD` code; MVP entry and
  reporting use company base currency only.
- **Fiscal-year start:** January
- **Company time zone:** `America/Los_Angeles`, the IANA identifier for the
  confirmed US Pacific time zone.
- **Affected phases:** 1, 2, 4, 7
- **Specification impact:** Replaces temporary defaults with production-intent
  settings; preserves the specification's UTC persistence rule.
- **Approval source:** User-provided values and confirmed default policy.

### D-003 — Access and visibility defaults

- **Date/status:** 2026-10-11 — Confirmed
- Manager visibility includes all recursive reporting descendants.
- Sensitive-data exports default to Manager/Director/Admin roles according to
  the object/action matrix. Export always remains a separate permission.
- Converted leads remain available as history and origin references but are
  hidden from active lead queues by default.
- **Affected phases:** 5, 6, 7, 8
- **Specification impact:** Confirms the defaults already proposed by the
  architecture.
- **Approval source:** User selection.

### D-004 — Existing Python dependencies

- **Date/status:** 2026-10-11 — Confirmed
- Preserve the existing AI-agent dependencies in `pyproject.toml`; add the
  Django CRM and quality dependencies alongside them.
- Phase 0 must test the combined dependency lock for version conflicts,
  platform compatibility, install size, and known vulnerabilities.
- The current project metadata name is `agents`; whether the distribution name
  should become `glidecrm` is a Phase 0 design decision and must not be changed
  silently.
- **Affected phase:** 0
- **Specification impact:** The architecture only names CRM dependencies. This
  intentionally retains a larger pre-existing environment.
- **Approval source:** User selection.

### D-005 — CI and test toolchain

- **Date/status:** 2026-10-11 — Confirmed
- Use GitHub Actions with MySQL 8.4, Ruff, pytest-django, and Playwright browser
  smoke tests.
- Acceptance CI runs migrations and tests against MySQL, not SQLite.
- **Affected phases:** 0–9
- **Specification impact:** Selects concrete tools where the architecture left
  pytest and browser tooling optional.
- **Approval source:** User selection.

### D-006 — Deployment and post-MVP scope

- **Date/status:** 2026-10-11 — Confirmed
- Keep cloud design provider-neutral until a provider decision is made before
  Phase 9.
- Treat every Phase 10 module as a separate, approved post-pilot project.
- Defer Microsoft 365 licensing, tenant policy, app registration, consent, and
  module priority until post-pilot planning.
- **Affected phases:** 9 and 10
- **Specification impact:** Prevents an unapproved provider or Microsoft
  integration choice from entering MVP scope.
- **Approval source:** User selection.

### D-007 — Progress reporting

- **Date/status:** 2026-10-11 — Confirmed
- Track both gate status and percentages in `DEVELOPMENT_STATUS.md`.
- Phase percentage equals reproducibly passed gate items divided by that
  phase's total gate items.
- Overall MVP percentage equals passed gate items divided by all 69 gate items
  in Phases 0–9. Phase 10 is reported separately.
- **Affected phases:** 0–10
- **Specification impact:** Adds an objective progress convention not defined
  in the architecture.
- **Approval source:** User selected combined gate and percentage tracking;
  the counting formula makes that selection reproducible.

### D-008 — Python distribution and Django package identity

- **Date/status:** 2026-10-11 — Confirmed
- Rename the Python distribution from the unrelated `agents` value to
  `glidecrm`.
- Use `glidecrm` as the Django project/settings package and keep the architecture
  app boundaries as top-level Django apps.
- Preserve all existing AI dependencies while adding locked CRM and test
  dependencies.
- **Affected phase:** 0
- **Specification impact:** Clarifies project packaging without changing the
  selected application architecture.
- **Approval source:** User selection before Phase 0 implementation.

### D-009 — Identity models live in the identity app

- **Date/status:** 2026-10-11 — Confirmed during Phase 1 design
- Internal users, roles, company settings, and login throttles live in the
  `identity` app. Its initial migration creates the custom user, which Django
  requires before `admin` migrations can reference it.
- The `accounts` app remains reserved for CRM customer and prospect records.
- `AUTH_USER_MODEL` is `identity.User`, with a manager relationship and an
  Admin or Standard User role. Team membership remains a Phase 6 addition.
- GlideCRM Admin is an application role, not Django staff/superuser access.
  The Django admin route is not exposed; company and user changes use audited
  application services.
- Development databases created before this user model must be recreated.
  No production user data exists.
- **Affected phases:** 1 and 5
- **Specification impact:** Preserves the architecture's user fields while
  avoiding a name collision with the CRM Account module.
- **Approval source:** Phase 1 design required before implementation.

### D-010 — Development password-reset email

- **Date/status:** 2026-10-11 — Confirmed during Phase 1 design
- Development uses Django's console email backend. Tests use the in-memory
  backend.
- Administrators may create a user with a temporary password or send a
  single-use invitation, and may send a later password reset. All three use
  the same configured backend and are audited.
- Reset links expire after one hour and become invalid after use.
- A production email provider and failure-alert owner are still required
  before production password reset is enabled.
- **Affected phase:** 1
- **Specification impact:** Implements the reset workflow without selecting an
  unapproved production email service.
- **Approval source:** Phase 1 delivery plan.

### D-011 — Phase 2 lead-linked deals

- **Date/status:** 2026-10-11 — Confirmed from the Phase 2 delivery boundary
- A Deal requires a Lead. It has no Account link until Phase 5, so sample deals
  `deal-2001` and `deal-2003` are not seeded.
- Phase 2 validates frozen taxonomy keys, money, currency, dates, owners, and
  record versions. Stage transition rules, stage history, Kanban, BANT, OEM
  fields, and conversion remain later phases. `stage_entered_at` records only
  the current stage entry.
- Admin scope is all records. Standard User scope is records they own.
  Manager-tree visibility remains Phase 6.
- List views must stay free of per-row queries. The timed list target at
  500,000 rows remains a Phase 9 measurement. On 2026-10-11 the user accepted
  that deferral because that volume is not expected soon. Phase 2 instead
  proved the Lead and Deal list query counts do not grow with the rows on the
  page.
- Seed and API keys use this document's uppercase taxonomy. The architecture
  sample's lowercase source names are illustrative only.
- **Affected phases:** 2, 3, 5, 6, and 9
- **Specification impact:** Preserves the Phase 2 exit gate that a Deal cannot
  be orphaned or attached to an Account yet.
- **Approval source:** Phase 2 delivery plan.

### D-012 — Phase 3 protected stage workflow

- **Date/status:** 2026-10-11 — Confirmed by proceeding from Phase 2 into Phase 3
- Lead and deal stage graphs are system-protected. Picklist labels stay
  editable. Retiring a value blocks it as a new transition target. The lead
  and deal edit forms cannot change stage; the transition service is the only
  stage writer, and the list, detail form, and Kanban all call it.
- Interactive create always starts at `NEW`. Synthetic fixtures also create at
  `NEW`, then use an audited Admin correction to establish their known stage.
  Phase 3 migration records a baseline history row for pre-existing records.
- The architecture's explicit “any active stage” rules for Nurturing,
  Unqualified, and Archived take precedence where its state diagram omits an
  edge. Unqualified remains terminal for ordinary users.
- Activity and task side effects stay in Phase 4. Primary contact stays in
  Phase 5. Until those phases, contact, discovery, and proposal gates use the
  data already on the record plus a reason: contact substatus and a channel,
  BANT statuses, amount, expected close date, and a close reason.
- Until manager roles arrive in Phase 6, Admin is the probability-override
  role and the correction role. An override requires `probability_reason`,
  which is stored with the probability snapshot.
  Reopening an unqualified lead is admin-only. Closed won, closed lost, and
  closed hold stay out of open pipeline totals.
- A Kanban drop posts the same transition endpoint and leaves the card in
  place until the server accepts the move.
- Stage history is append-only at the application model/queryset layer.
- **Affected phases:** 3, 4, 5, and 6
- **Specification impact:** Preserves the workflow exit gates while deferring
  activity, task, and primary-contact side effects to the phases that own them.
- **Approval source:** Phase 3 delivery plan.

### D-013 — Phase 4 activities, tasks, and reminders

- **Date/status:** 2026-10-11 — Confirmed by proceeding from Phase 3 into Phase 4
- **Decision:** An activity or task is one record. `ActivityLink` and `TaskLink`
  attach it to a lead or deal, and the same pair cannot be stored twice. The
  timeline of a record the user can already open shows every linked follow-up.
  Creating or changing a follow-up still uses owner scope.
- Quick-add on a lead or deal starts as a Call for that record. The `A` key
  focuses it only when the cursor is outside a form field.
- Task center buckets are overdue, due today, and upcoming, using the viewer's
  time zone. Complete and snooze are audited and bump the version. Naive form
  times are read in that user's zone; stored values stay UTC.
- Reminders are in-app rows, one per task, recipient, and effective due time.
  No email is sent. `run_due_jobs` still skips a repeated run in the same
  minute. A failed run stays `FAILED` and is retried on a later minute without
  creating a second reminder for a due time already delivered.
- A lead is stale after 14 days without a newer linked activity, and a deal
  after 21 days. Company administrators can change both thresholds. The list
  badge uses one grouped query for the current page.
- Synthetic `act-3002` and `task-4002` stay unseeded because they belong to
  account deal `deal-2001`, which Phase 2 does not create. `act-3001`,
  `act-3003`, and `task-4001` are seeded on the existing sample leads.
- Stage moves keep the Phase 3 reason-based gates. Requiring a logged activity
  or task before Contacted, Discovery, Proposal, or Closing is a later change
  so existing audited transitions stay valid.
- **Affected phases:** 4
- **Specification impact:** Keeps reminder email deferred until a provider is
  approved, and skips sample rows whose parent deal is not in the database.
- **Approval source:** User request to proceed with Phase 4.

### D-014 — Record age, time in stage, and lead temperature

- **Date/status:** 2026-10-11 — Confirmed by user review of the lead and deal pages
- **Decision:** Age is calculated from `created_at`. Time in the current stage is
  calculated from `stage_entered_at`. Stage history states the stage that
  started, or the move and the time spent in the previous stage. A baseline
  row with no previous stage does not say “by after 0 seconds” or show the
  internal “Phase 3 baseline” label.
- Leads use Hot, Warm, and Cold, defaulting to Warm when a create request
  omits one. Sample leads are Hot, Warm, or Cold as seeded. D-015 renames
  this field to Lead rating and gives deals a separate confidence list.
- A task can be added from the lead, the deal, or the task list.
- **Affected phases:** 2, 3, and 4
- **Specification impact:** Adds lead temperature, which the architecture
  model lists on deals only.
- **Approval source:** User request after using the lead and deal pages.

### D-015 — Lead rating and deal confidence

- **Date/status:** 2026-10-11 — Confirmed by user request
- **Decision:** The lead field is Lead rating and keeps Hot, Warm, and Cold.
  The deal field is Deal confidence. Stored deal values move from Hot, Warm,
  and Cold to High, Medium, and Low (`HOT` to `HIGH`, `WARM` to `MEDIUM`,
  `COLD` to `LOW`). The shared temperature list is retired.
- **Affected phases:** 2 and 4
- **Specification impact:** Replaces the architecture's deal temperature field
  and the Hot/Warm/Cold report category for deals. Lead rating remains the
  D-014 addition under the new name.
- **Approval source:** User request to rename the fields and deal values.

### D-016 — Accounts, contacts, and lead conversion

- **Date/status:** 2026-10-11 — Confirmed by starting Phase 5
- **Decision:** An Account and its Contacts can be created directly. A Deal
  belongs to one Lead or one Account, never both and never neither. Conversion
  keeps the Lead, records the Account and Contact it produced, and can move
  open Deals onto the Account while keeping the originating Lead on
  `converted_from_lead`. Closed Deals stay on the Lead.
- Duplicate Account matches use the website domain, then the normalized name,
  then a shared name token. Contact matches use normalized email, then the
  same name and title. Matches are shown with a score and reasons. Nothing is
  merged or overwritten unless the person chooses an existing record and, for
  each different field, chooses keep or use the lead value.
- A standard user can convert only onto a Customer or Prospect. An
  administrator can choose any account type. Account parent links and contact
  reporting lines cannot cycle. A contact reports inside one account unless an
  administrator overrides that. One primary contact is enforced by locking the
  account row. A second conversion submit returns the first result. The
  conversion work is one database transaction.
- Converted leads stay readable, including from the lead page and
  `?converted=1`, and stay out of the default lead queue.
- **Affected phase:** 5
- **Specification impact:** Supersedes the Phase 2 limit in D-011 that a Deal
  cannot link to an Account. Manager-tree visibility stays in Phase 6.
- **Approval source:** Phase 5 delivery plan, started by the request to baseline
  the previous work and begin the next phase. D-017 changes what happens to
  the deal that itself just closed.

### D-017 — Independent stages and conversion on deal close

- **Date/status:** 2026-10-11 — Confirmed by user request
- **Decision:** Lead stages and deal stages change independently. A lead stage
  change does not move a deal, create an account, or convert the lead. A deal
  stage change does not move the lead.
- Closed Won and Closed Lost convert the deal's lead in the same transaction
  when that deal still belongs to a lead. The lead stage stays unchanged. An
  existing account is used only when the website domain matches, or the
  normalized company name matches exactly. The lead is added as a contact on
  that account. An existing contact with the same email is reused and its
  fields are not overwritten. Otherwise a new account is created: Customer for
  Closed Won, Prospect for Closed Lost. The person leaves the active lead list
  and is listed under that account on the account page and the Contacts page. A similar name is not reused. Closed
  Hold does not convert the lead. Only the deal that closed moves onto the
  account. A later close for the same lead reuses the first account and contact.
- The manual conversion wizard remains for conversion before a deal closes.
  That wizard still requires an explicit choice when it finds a duplicate.
- **Affected phases:** 3 and 5
- **Specification impact:** Updates the lead and deal state machines and the
  conversion workflow in `architecture-MVP-spec.md`. Supersedes the D-016
  statement that a closed deal stays on the lead, for the deal that just closed.
- **Approval source:** User request to untie the stage machines and convert a
  lead when its deal closes.

### D-018 — Role matrix, teams, and audit

- **Date/status:** 2026-10-11 — Recorded for Phase 6
- **Decision:** The architecture role matrix is enforced on every record path.
  Phase 1 Standard User stays beside that matrix, with create, read, update,
  and soft-delete on records they own, and no export.
- Team membership is `Team.members`. A person may belong to more than one
  active team. `TEAM` scope is the union of those members. Sales Director
  visibility follows the manager tree, including indirect reports, and does
  not include an unrelated branch.
- Sales Director may correct a stage and override probability. SDR/BDR may
  create a deal only when the source lead is SQL Ready. Export is refused
  without the separate export grant.
- Denial and privilege logs store the actor, object, action, and reason.
  They do not store CRM field values. Audit rows cannot be changed. Active
  administrators are reviewed from the administrator review page.
- **Affected phase:** 6
- **Specification impact:** `architecture-MVP-spec.md` records versioned
  grants, multi-team membership, and the Standard User role next to the matrix.
- **Approval source:** Phase 6 implementation of the architecture matrix,
  keeping the Phase 1 Standard User role.

### D-019 — Task hold, activity correction, and list sorting

- **Date/status:** 2026-10-11 — Confirmed by user request
- **Decision:** A task can be completed, snoozed, put on hold, resumed, cancelled,
  or soft-deleted. Hold is a pause: the task leaves the due lists, reminders
  stop, and Resume returns it to Open. Cancel marks it Cancelled. Delete is a
  soft delete and requires the delete grant plus a reason. The task list shows
  the linked lead, contact, and deal.
- An activity on a timeline can be edited or soft-deleted when it was added by
  mistake. The activity body stays out of the audit snapshot.
- Record detail pages show summary fields in two columns. List pages can sort
  by the fields that describe the work: age, stage, rating, follow-up, owner,
  and company for leads; amount, stage, confidence, expected close, and owner
  for deals; name, type, and owner for accounts; account, name, and title for
  contacts; due date, priority, owner, and title for tasks.
- **Affected phases:** 4 and 7
- **Specification impact:** Task status, task center, activity timeline, and
  lead list sorting in `architecture-MVP-spec.md`. Extends D-013; it does not
  replace the overdue, due, and upcoming buckets.
- **Approval source:** User request to show task links, add cancel, hold, and
  delete, edit or delete activities, use two columns on detail pages, and add
  list sorting.

### D-020 — Task lists and displayed dates

- **Date/status:** 2026-10-11 — Confirmed by user request
- **Decision:** The task page opens on every open task, so overdue work and
  later work are both visible. Overdue means the due time has already passed.
  Due today means the due time is still later today. Upcoming means the due
  time is after today. Held, completed, and cancelled tasks each have their
  own list.
- Dates and times shown in the application use mm-dd-yyyy, hh:mm AM/PM in the
  viewer's time zone. Stored values stay UTC. Form controls that require an
  ISO value keep that machine format.
- **Affected phases:** 4
- **Specification impact:** Task center and the time-zone display rule in
  `architecture-MVP-spec.md`. Extends D-013; the overdue, due today, and
  upcoming lists remain.
- **Approval source:** User request to show overdue and upcoming tasks by
  default, to keep completed tasks visible, and to use mm-dd-yyyy, hh:mm AM/PM.

### D-021 — Settings menu and Help

- **Date/status:** 2026-10-11 — Confirmed by user request
- **Decision:** Company, Teams, Users, Roles, and Audit are reached from
  Settings. Audit remains available to every signed-in user, limited to the
  history they can read. Teams and Users remain available to administrators
  and sales directors. Company and Roles remain administrator-only. Help sits
  next to Log out and explains how to use the CRM.
- **Affected phases:** 1 and 6
- **Specification impact:** Global shell and Admin rows in
  `architecture-MVP-spec.md`.
- **Approval source:** User request to group administration under Settings and
  add Help beside Log out.

### D-022 — Money display

- **Date/status:** 2026-10-11 — Confirmed by user request
- **Decision:** Amounts shown in the application are rounded to whole dollars
  and written as `$ 12,500`. The dollar sign comes first, with a space, and
  thousands are separated by commas. Stored amounts keep cents. The company
  currency remains USD.
- **Affected phases:** 2 and 3
- **Specification impact:** Currency display rule in `architecture-MVP-spec.md`.
- **Approval source:** User request to drop decimals, put the currency symbol
  in front, and use thousands separators.

### D-023 — Reports and dashboards

- **Date/status:** 2026-10-11 — Implemented with Phase 7
- **Decision:** Reports total the same lead, deal, account, activity, and
  task records the viewer can already read. An administrator opens reports
  through the report Administer grant. A blank date range includes every
  record. Forecast groups open deals by the quarter of the expected close
  date and keeps deals with no expected close date visible as Unscheduled.
  Date bounds are inclusive viewer-local days. Each report names the companies
  or accounts behind the total. A parent account rollup adds
  each descendant’s open amount once, and the company total is the sum of
  own amounts. If the prior period has no wins, the comparison shows N/A.
  Export writes `report.exported` with the actor, filters, fields, and row
  count, and stores no CRM field values. The dashboard query budget is 30.
  Sales-cycle median and time-in-stage reports stay out of this release.
- **Affected phases:** 7
- **Specification impact:** Section 8 of `architecture-MVP-spec.md`.
- **Approval source:** Phase 7 gate in the delivery plan, using the January
  fiscal year and existing record scope.

### D-024 — CSV import templates

- **Date/status:** 2026-10-11 — Implemented with Phase 8
- **Decision:** Leads, accounts, and contacts import from UTF-8 CSV.
  The template files are `imports/csv_templates/leads.csv`,
  `accounts.csv`, and `contacts.csv`. Lines starting with `#` say whether
  each column is required or optional and which key or format to use.
  The sample row is skipped while `row_action` is `example`. Preview writes
  no lead, account, or contact. A match uses `external_id` first, then an
  exact email or an exact account domain or name. Skip, Update, and Create
  are the only policies. Commit saves 200 rows at a time. Reusing a retry
  key does not insert those rows again. Rollback soft-deletes rows that
  were not edited later and leaves edited rows in place. Workbooks are
  not accepted yet.
- **Affected phases:** 8
- **Specification impact:** Section 9 of `architecture-MVP-spec.md`.
- **Approval source:** User request for lead, contact, and account CSV
  templates, and the Phase 8 gate.

### D-025 — Stage and conversion fields

- **Date/status:** 2026-10-11 — Implemented
- **Decision:** A stage form shows only the fields that destination requires,
  and an asterisk marks each one. Contacted, nurturing, unqualified,
  archived, SQL Ready, and reactivation still require the note, reason, or
  follow-up that gives the stage its meaning. Qualified still requires an
  amount and an expected close date. Budget, Authority, Need, and Timeline
  stay on every deal and are optional: set each one when it is known and
  leave Unknown when it is not. They do not block a stage change. Discovery
  requires a note. Closed Won requires
  a final amount and close date. Closed Lost and Closed Hold require a
  reason from the matching list. There is no separate approval before a
  stage change or a close. The lead board and the deal board do not change
  the stage. Update stage opens the record page, and that page collects
  the fields. Manual conversion requires an account name and type
  when creating an account. A confirmation is asked only when an account
  or contact already matches.
- **Affected phases:** 3 and 5
- **Specification impact:** Deal stage table in section 4 of
  `architecture-MVP-spec.md`.
- **Approval source:** User request to mark required fields and drop
  stage-change fields that do not change the decision.

### D-026 — User email and phone

- **Date/status:** 2026-10-12 — Implemented
- **Decision:** An internal user keeps a required email and an optional phone.
  Password reset and invitation instructions are addressed to that email.
  Phone is stored for later use and is not a delivery channel. Delivery
  still follows D-010: the development backend writes the message to the
  application log until a production mail provider is selected.
- **Affected phase:** 1
- **Specification impact:** User row in section 3 of
  `architecture-MVP-spec.md`.
- **Approval source:** User request to store email and phone on the user.

### D-027 — Release gate before a cloud host

- **Date/status:** 2026-10-12 — In progress
- **Decision:** The cloud provider, managed MySQL service, and off-host backup
  target stay unselected, as D-006 required. No production data moves until
  those are named. The release gate that must pass first is in place: the
  release settings profile passes `check --deploy`, a backup contains the
  database and uploads and is encrypted before it leaves the machine, a
  restore is proven on an empty database, and a rollback restores that backup
  plus the previous image. Satish, the company administrator, is the interim
  owner of every operational alert until a second incident contact is named.
  HSTS stays off until HTTPS works on the final host.
- **Affected phase:** 9
- **Specification impact:** Uses the cloud-mode and backup rules in section 11
  of `architecture-MVP-spec.md` without choosing a vendor.
- **Approval source:** User request to proceed with the next step.

### D-028 — 500,000-lead list timing

- **Date/status:** 2026-10-12 — Measured on the local Docker MySQL 8.4
- **Decision:** The cloud host stays unselected. The 500,000-row list
  measurement runs on this machine, in database `glidecrm_perf`, and does not
  write to the application database. The open lead list and the New-stage
  list must stay under 2 seconds. The first measurement was 25.808 seconds
  and 8.363 seconds because the page sorted every column of the full set.
  The list now resolves the page by primary key, then loads those rows and
  their owners. Indexes `leads_open_recent_idx` and `leads_open_stage_idx`
  cover the open-list filters and order. The remeasure was 0.400 seconds for
  the open list and 0.180 seconds for New. The lead board still loads every
  matching lead and is not this measurement.
- **Affected phases:** 2 and 9
- **Specification impact:** Confirms the section 11 list target for the paged
  lead list. No cache or rollup table was added.
- **Approval source:** User asked to keep hardening on this machine and
  include the 500,000-record list measurement.

### D-029 — Product name GlideCRM

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** The product, page titles, Python distribution, and Django
  project package are GlideCRM / `glidecrm`. This replaces the name chosen in
  D-008. The application database, database user, health-check service name,
  and backup confirmation token use `glidecrm` as well.
- **Rationale:** Flux CRM is an existing product, so this CRM cannot keep that
  name.
- **Affected phases:** 0–9
- **Specification impact:** The package boundary in D-008 stays the same. Only
  the name changes. App modules such as leads, accounts, and sales are
  unchanged.
- **Approval source:** User request to replace Flux with Glide everywhere,
  including the code.
- **Migration/rollback impact:** The local application database and its login
  were renamed in place. Existing rows were not rewritten.

### D-030 — Deal confidence follows win probability

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Deal confidence is High when win probability is 80% or more,
  Medium from 40% up to 80%, and Low under 40%. The system sets confidence
  whenever a deal is saved or its stage changes. The person can change the
  win probability and cannot set confidence directly. The Deals page shows
  deals by stage and confidence under Pipeline, deals by age and quarter
  under Timing, and deals by sales owner under Ownership.
- **Rationale:** Confidence was a separate choice, so it could disagree with
  the probability used for the forecast.
- **Affected phases:** 4 and 7
- **Specification impact:** Replaces the user-entered confidence in D-015.
  The stored values remain High, Medium, and Low.
- **Approval source:** User request to derive confidence from win probability
  and to group the new deal reports on the Deals page.
- **Migration/rollback impact:** Existing deals are updated from their current
  probability. The previous confidence choice is not kept.

### D-031 — Account and contact edit, with export ids

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** An account and a contact can be edited. Name and type are
  required on an account. First name and last name are required on a contact,
  and the account is required when editing a contact. GlideCRM assigns the
  record id. That id is not shown and is not typed. Lead, account, and contact
  exports include it. A contact export also includes the account id.
- **Rationale:** Those records could be added but not corrected, and an export
  could not identify them by the application id.
- **Affected phases:** 5 and 8
- **Specification impact:** Account and contact screens gain edit. Export adds
  the UUID columns beside the existing external id.
- **Approval source:** User request to edit accounts and contacts, hide the
  assigned ids, and include those ids in the lead, account, and contact exports.
- **Migration/rollback impact:** No stored data changes. Existing ids stay as
  they are.

### D-032 — Client account type and industry labels

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Account type gains Client (`CLIENT`). The industry list,
  shared by leads and accounts, gains Insurance, Automotive, Hospitality &
  Travel, and Technology & SaaS. The Retail label becomes Retail &
  E-Commerce. The stored key stays `RETAIL`.
- **Rationale:** The lists did not cover these businesses, and Retail was
  narrower than the work being tracked.
- **Affected phases:** 2 and 5
- **Specification impact:** Adds one account type and four industry keys, and
  renames the Retail label. Existing Retail rows keep their key.
- **Approval source:** User request to add Client and the industry names, and
  to rename Retail.
- **Migration/rollback impact:** New picklist rows are added. The Retail
  label is rewritten. Account rows are not rewritten.

### D-033 — Owner name on records and imports

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Leads, accounts, contacts, deals, activities, and tasks show
  the owner's name. Lead, account, and contact import and export use that
  name for the owner column. The login username is not accepted in that
  column. A blank owner still assigns the row to the person importing it.
  Two active users with the same name are rejected.
- **Rationale:** The name on the user is what people type and read. The
  login username is a separate sign-in value.
- **Affected phases:** 2, 5, and 8
- **Specification impact:** The owner column in the CSV templates names the
  person. Screens that already showed that name stay as they are.
- **Approval source:** User request to show the owner's name on records and
  to match import owners by that name.
- **Migration/rollback impact:** No stored owner changes. Existing rows keep
  the same owner.

### D-034 — Client accounts become Customer

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Client and Customer are one account type, Customer
  (`CUSTOMER`). Accounts stored as Client are rewritten to Customer. Import
  rollback snapshots that still say Client are rewritten the same way. The
  audit log is left as it was written.
- **Rationale:** The two types described the same relationship.
- **Affected phases:** 5
- **Specification impact:** Removes Client from the account type list.
- **Approval source:** User request to merge Client and Customer and name
  the result Customer.
- **Migration/rollback impact:** Existing Client rows become Customer. The
  reverse does not restore the Client value.

### D-035 — Delete requires a reason

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Accounts and contacts can be soft-deleted from their pages.
  The person must enter a reason of at least 3 characters. An account that
  still has child accounts, contacts, or deals cannot be deleted. A contact
  who is still the primary contact on a deal, or who other contacts report
  to, cannot be deleted. Leads, deals, activities, and tasks already required
  a reason; those delete actions stay on the record page.
- **Rationale:** A delete should be explainable, and related records should
  not be removed along with the parent.
- **Affected phases:** 5
- **Specification impact:** Account and contact soft delete requires a reason
  and refuses while dependent records remain.
- **Approval source:** User request to add delete for contacts, accounts,
  deals, and similar records, and to require a reason first.
- **Migration/rollback impact:** No data change. Deleted rows stay in the
  database with the reason and the deletion time.

### D-036 — Delete sits at the bottom and needs one confirmation

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Delete for a lead, deal, account, contact, activity, or task
  is at the bottom of that record’s page. The person enters a reason and
  checks one confirmation. The record is removed from lists only after both.
- **Rationale:** Delete should be available without sitting above the record,
  and a single click should not be enough. One checkbox is the confirmation.
- **Affected phases:** 5
- **Specification impact:** Account and contact delete, and the existing
  lead, deal, activity, and task delete actions, require one confirmation
  in addition to the reason.
- **Approval source:** User request to move delete to the bottom of the
  screen and add a double confirmation.
- **Migration/rollback impact:** No data change.

### D-037 — Lead stages for an IT sales flow

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Lead stages are New, Contacted, MQL, Demo/POC Scheduled,
  SQL, Nurturing, Unqualified, and Archived. SQL Ready is renamed to SQL.
  SQL Reactivation is merged into Nurturing with nurture reason Reactivation.
  Demo/POC Scheduled requires a scheduled date and a technical contact name.
  MQL still requires a qualification note. Company size, current tools,
  budget range, and timeline on that move are optional. Unqualified uses
  No Budget, No Technical Fit, Wrong Decision-Maker, Security-Compliance
  Mismatch, or Timing. Archived is for a lead that went silent. Unqualified
  is for a lead that is not a fit. Reopening Unqualified stays
  administrator-only.
- **Rationale:** The previous list skipped the demo step used in IT lead
  flow and split reactivation into its own stage.
- **Affected phases:** 3
- **Specification impact:** Lead state machine, stage gates, and the
  starter nurture, disqualification, tools, budget, and timeline lists.
- **Approval source:** User request to update lead stages, map current
  records, and update the database.
- **Migration/rollback impact:** Stored SQL Ready becomes SQL. Stored SQL
  Reactivation becomes Nurturing with reason Reactivation when that reason
  was blank. No Authority becomes Wrong Decision-Maker. No Fit, No Need,
  bad data, duplicate, territory, and other old reasons become No Technical
  Fit. Stage history for leads is rewritten the same
  way. The audit log is left as it was written. The reverse does not
  restore the old stage keys.

### D-038 — Deal stages for an IT sales flow

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** Deal stages are New, Discovery, Qualified, Technical
  Evaluation, Proposal, Negotiation, Closing, Closed Won, Closed Lost, and
  Closed Hold. Contacted is renamed to Discovery so it does not collide with
  the lead stage of the same name. The previous Discovery stage, which sat
  after Qualified, becomes Technical Evaluation. That stage requires a POC
  or trial start date, a technical stakeholder name, and a success-criteria
  note. Negotiation requires a terms note and an expected close date.
  Closed Lost reasons are Price, Competitor, No Technical Fit, Timing, and
  Lost to Internal Build. Closed Hold is unchanged, including the reopen
  reason. New remains the landing stage before Discovery.
- **Rationale:** IT deals need a technical evaluation step, and Discovery
  should mean requirements gathering rather than a second contact log.
- **Affected phases:** 3
- **Specification impact:** Deal state machine, stage gates, default
  probabilities, and the Closed Lost reason list.
- **Approval source:** User request to update deal stages and fix current
  records.
- **Migration/rollback impact:** Stored Discovery becomes Technical
  Evaluation first, then stored Contacted becomes Discovery. Requirements
  gap becomes No Technical Fit. Internally cancelled becomes Lost to
  Internal Build. No decision becomes Timing. Relationship becomes
  Competitor. On Closed Lost only, Budget becomes Price and Other becomes
  No Technical Fit. Hold reasons are not rewritten. Stage history for deals
  is rewritten the same way. Lead stages are not rewritten. The audit log
  is left as it was written. The reverse does not restore the old stage
  keys.

### D-039 — Demo lead stage label

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** The lead stage Demo/POC Scheduled is labeled Demo. The
  stored key stays DEMO_POC. Moving there still requires a demo date and a
  technical contact name.
- **Rationale:** The shorter name is what should appear on the lead screens.
- **Affected phases:** 3
- **Specification impact:** Lead stage label only.
- **Approval source:** User request to rename the stage and update the screens.
- **Migration/rollback impact:** The picklist label changes. Lead rows and
  stage history are not rewritten. The reverse restores the previous label.

### D-040 — POC/Tech Evaluation deal stage label

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** The deal stage Technical Evaluation is labeled POC/Tech
  Evaluation. The stored key stays TECHNICAL_EVALUATION. The required fields
  stay a POC or trial start date, a technical stakeholder name, and a
  success-criteria note.
- **Rationale:** The name on the deal screens should say POC/Tech Evaluation.
- **Affected phases:** 3
- **Specification impact:** Deal stage label only.
- **Approval source:** User request to rename the stage and update the screens
  and Help.
- **Migration/rollback impact:** The picklist label changes. Deal rows and
  stage history are not rewritten. The reverse restores the previous label.

### D-041 — Deals on an account require a contact

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** A deal can be added from an account as well as from a lead.
  An account deal requires one contact that already belongs to that account.
  From the Deals page, the form asks whether the deal is linked to a lead
  or an account, then lists leads or that account’s contacts.
  Amount, win probability, confidence, and stage rules match a deal on a
  lead. Closing an account deal does not convert a lead. The account and
  the contact stay on the deal. The contact can be changed to another
  contact on the same account.
- **Rationale:** Account work needs the same deal pipeline, tied to a
  person on that account.
- **Affected phases:** 3 and 5
- **Specification impact:** Deal source and the New-stage gate.
- **Approval source:** User request to add deals on an account through a
  contact, with the rest of the deal behavior unchanged.
- **Migration/rollback impact:** No schema change. Existing lead deals and
  converted deals stay as they are. Removing the screen hides the path;
  stored account deals remain valid.

### D-042 — Contact phones copy from the lead

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** A contact stores a work phone and a mobile phone. Converting
  a lead, including when a deal closes, copies the lead’s title, email,
  work phone, and mobile phone onto the new contact. An existing contact
  keeps a phone it already has. A blank phone is filled from the lead.
- **Rationale:** The person details on the lead should still be on the
  contact after conversion.
- **Affected phases:** 5
- **Specification impact:** Contact fields and lead conversion.
- **Approval source:** User request to carry lead details, including phone
  numbers, onto the contact.
- **Migration/rollback impact:** Two optional text columns on the contact.
  Existing contacts keep blank phones. The reverse drops the columns.

### D-043 — Wins use the actual close date

- **Date/status:** 2026-10-12 — Confirmed
- **Decision:** A deal stores an actual close date, separate from the
  expected close date. Closed Won requires that date and the final amount.
  Won this quarter, won this year, and the won rows of won/lost use that
  date. They do not use the day the stage changed to Closed Won. Deals
  already won start with the day the stage was moved, and that date can
  be corrected.
- **Rationale:** A deal can be marked won later than the day it closed.
- **Affected phases:** 3 and 7
- **Specification impact:** Deal close date and dashboard win periods.
- **Approval source:** User request to track the actual close date instead
  of the Closed Won stage change.
- **Migration/rollback impact:** One optional date column. Existing wins
  are filled from the Closed Won stage change, in America/Los_Angeles.
  The reverse clears and drops the column.

### D-044 — Optional address on leads, accounts, and contacts

- **Date/status:** 2026-10-14 — Confirmed
- **Decision:** A lead, an account, and a contact each store one optional
  address: street, city, state, postal code, and country. None of those
  parts is required. The account uses this one address. Converting a lead
  copies the address onto a new account and a new contact. An existing
  account or contact keeps an address it already has. A blank address is
  filled from the lead. Import templates include the same columns, and
  the state column is named region.
- **Rationale:** The address was missing from the forms even where the
  lead already had a place to store it.
- **Affected phases:** 2, 5, and 8
- **Specification impact:** Lead, account, and contact address fields, and
  lead conversion.
- **Approval source:** User request to add optional address information
  for leads, accounts, and contacts, then update import and help.
- **Migration/rollback impact:** The lead address column already existed.
  Account and contact gain one optional JSON address, empty until entered.
  The reverse drops those two columns.

### D-045 — Phone numbers use (XXX) XXX-XXXX

- **Date/status:** 2026-10-14 — Confirmed
- **Decision:** A phone on a lead, account, contact, or user is stored and
  shown as (XXX) XXX-XXXX. A blank phone stays blank. Ten digits are
  accepted, and an 11-digit number that starts with 1 drops that leading
  1. Import uses the same format.
- **Rationale:** Phone numbers were entered and shown in mixed formats.
- **Affected phases:** 2, 5, and 6
- **Specification impact:** Lead, account, contact, and user phone fields.
- **Approval source:** User request to use (XXX) XXX-XXXX on input and
  display.
- **Migration/rollback impact:** Existing 10-digit numbers are rewritten
  to that format. The reverse leaves the rewritten values in place.

### D-046 — Lead and contact email is required

- **Date/status:** 2026-10-14 — Confirmed
- **Decision:** A lead and a contact each require an email address. A blank
  email is rejected on the form, the API, conversion, and import. Email
  stays normalized for matching and is not unique.
- **Rationale:** Every lead and contact needs an address that can be used
  to match and follow up.
- **Affected phases:** 2, 5, and 8
- **Specification impact:** Lead and contact `email` are required.
- **Approval source:** User request to make email mandatory for leads and
  contacts.
- **Migration/rollback impact:** New and edited records must include an
  email. A record saved earlier with a blank email stays until it is
  edited, and that edit must supply an email. The reverse allows a blank
  email again.

### D-047 — Activities record who, when, and notes

- **Date/status:** 2026-10-16 — Confirmed
- **Decision:** A logged activity is a call, an email, or a meeting. It
  requires who it was with and when it happened. Notes are optional. Note
  is not an activity type. A task has optional notes, and an open or held
  task can be edited. Edit sits next to Complete. The task delete button
  sits on the same line as the confirmation.
- **Rationale:** Follow-up needed the person, the time, and notes, and
  tasks could not be corrected after they were added.
- **Affected phases:** 4
- **Specification impact:** Activity type, `with_whom`, activity notes, and
  task edit.
- **Approval source:** User request to edit tasks, capture activity notes,
  who the activity was with, and when it happened, and to remove Note as
  an activity type.
- **Migration/rollback impact:** Activities gain `with_whom`, blank until
  entered. A row saved earlier as Note stays readable. The reverse drops
  `with_whom`.

### D-048 — Task actions stay on the Tasks screen

- **Date/status:** 2026-10-16 — Confirmed
- **Decision:** The Tasks list shows the title in bold. A lead, account, or
  deal can complete or edit a task. Hold, resume, snooze, cancel, and
  delete stay on the Tasks screen. Task notes are not shown on a deal.
  Delete sits next to Edit on an activity.
- **Rationale:** The deal page repeated task controls and notes that belong
  on the Tasks screen.
- **Affected phases:** 4
- **Specification impact:** Task list, record timeline, and activity delete.
- **Approval source:** User request to simplify the deal page and keep task
  controls on the Tasks screen.
- **Migration/rollback impact:** No data change.

### D-049 — An activity is with a contact or a lead

- **Date/status:** 2026-10-16 — Confirmed
- **Decision:** Who an activity was with is one existing contact or one
  existing lead. A name that is not already a contact or lead is not
  accepted. Create that person first, then choose them. A name saved
  earlier stays visible until the activity is edited, and a unique saved
  name is linked when it matches one contact or one lead.
- **Rationale:** The person on an activity has to be someone the CRM
  already knows, so the follow-up stays attached to a record.
- **Affected phases:** 4
- **Specification impact:** Activity `with_whom` is a contact or a lead.
- **Approval source:** User request to link “with whom” to a contact or
  lead and to require that person to be created first.
- **Migration/rollback impact:** Activities gain `with_contact` and
  `with_lead`. A unique matching name is linked. The reverse drops both
  links and keeps the saved name.

### D-050 — Note is an activity type again

- **Date/status:** 2026-10-16 — Confirmed
- **Decision:** A logged activity can be a call, an email, a meeting, or
  a note. It still requires who it was with and when it happened. The
  notes field stays optional on every activity.
- **Rationale:** A note is a follow-up of its own, separate from the
  notes written on a call, email, or meeting.
- **Affected phases:** 4
- **Specification impact:** Activity type includes Note.
- **Approval source:** User request to add notes back to activities.
- **Migration/rollback impact:** No data change. Note was already stored
  for older rows.

### D-051 — Lead company size replaces employee count

- **Date/status:** 2026-10-21 — Confirmed
- **Decision:** A lead does not store a separate employee count. Company
  size is the band that records how large the company is.
- **Rationale:** Company size already captures the same information.
- **Affected phases:** 2
- **Specification impact:** Lead profile drops `employee_count`.
- **Approval source:** User request to remove employee count from leads.
- **Migration/rollback impact:** The lead column is dropped. Stored counts
  are not kept. The reverse adds an empty column.

### D-052 — Open deals, sorted by confidence

- **Date/status:** 2026-10-21 — Confirmed
- **Decision:** The Deals page lists open deals only. The default order is
  confidence: High, then Medium, then Low. Closed Won, Closed Lost, and
  Closed Hold stay on the deal reports.
- **Rationale:** The working list is the open pipeline. Closed deals are
  already on the reports.
- **Affected phases:** 3 and 7
- **Specification impact:** Deals page scope and default sort.
- **Approval source:** User request to sort the deals list by confidence
  and leave closed deals off that page.
- **Migration/rollback impact:** No data change.

### D-053 — Completing a task asks for notes

- **Date/status:** 2026-10-21 — Confirmed
- **Decision:** Complete asks for notes. Notes entered there are added to
  the task. Leaving the field blank keeps the notes already saved.
- **Rationale:** The outcome of the task is recorded when the work is
  finished.
- **Affected phases:** 4
- **Specification impact:** Task complete action.
- **Approval source:** User request to ask for notes when completing a task.
- **Migration/rollback impact:** No data change.

## Starter taxonomy — version 1

The user approved a standard, admin-editable starter set. Keys are stable
machine values; labels may be edited. In-use values are retired, never deleted.
Changes after implementation require a migration/seed plan and a new decision
entry.

### Lead sources

- `WEB` — Website
- `REFERRAL` — Referral
- `PARTNER` — Partner
- `CONFERENCE_EVENT` — Conference/Event
- `OUTBOUND` — Outbound Prospecting
- `LIST_PURCHASE` — Purchased List
- `ORGANIC_SEARCH` — Organic Search
- `PAID_SEARCH` — Paid Search
- `SOCIAL` — Social Media
- `EMAIL_CAMPAIGN` — Email Campaign
- `OTHER` — Other

### Industries

- `INFORMATION_TECHNOLOGY` — Information Technology
- `TECHNOLOGY_SAAS` — Technology & SaaS
- `PROFESSIONAL_SERVICES` — Professional Services
- `HEALTHCARE` — Healthcare
- `FINANCIAL_SERVICES` — Financial Services
- `INSURANCE` — Insurance
- `MANUFACTURING` — Manufacturing
- `AUTOMOTIVE` — Automotive
- `RETAIL` — Retail & E-Commerce
- `HOSPITALITY_TRAVEL` — Hospitality & Travel
- `EDUCATION` — Education
- `GOVERNMENT` — Government
- `NONPROFIT` — Nonprofit
- `OTHER` — Other

### Company-size bands

- `1_10` — 1–10 employees
- `11_50` — 11–50 employees
- `51_200` — 51–200 employees
- `201_500` — 201–500 employees
- `501_1000` — 501–1,000 employees
- `1001_5000` — 1,001–5,000 employees
- `5001_PLUS` — 5,001+ employees
- `UNKNOWN` — Unknown

### Nurture reasons

- `TIMING` — Timing not right
- `BUDGET` — Budget not available
- `MQL_NOT_SALES_READY` — Marketing-qualified but not sales-ready
- `NO_RESPONSE` — Unable to re-engage
- `FUTURE_EVALUATION` — Evaluating in a future period
- `REACTIVATION` — Reactivation
- `OTHER` — Other

### Disqualification reasons

- `NO_BUDGET` — No Budget
- `NO_TECHNICAL_FIT` — No Technical Fit
- `WRONG_DECISION_MAKER` — Wrong Decision-Maker
- `SECURITY_COMPLIANCE` — Security-Compliance Mismatch
- `TIMING` — Timing

### Current tools

- `MICROSOFT_365` — Microsoft 365
- `AZURE` — Microsoft Azure
- `AWS` — Amazon Web Services
- `GOOGLE_CLOUD` — Google Cloud
- `ON_PREMISES` — On-premises
- `HYBRID` — Hybrid
- `UNKNOWN` — Unknown
- `OTHER` — Other

### Budget ranges

- `UNDER_25K` — Under $25,000
- `25K_100K` — $25,000–$100,000
- `100K_250K` — $100,000–$250,000
- `250K_PLUS` — $250,000 or more
- `UNKNOWN` — Unknown

### Buying timelines

- `IMMEDIATE` — Immediate
- `THIS_QUARTER` — This quarter
- `NEXT_QUARTER` — Next quarter
- `THIS_YEAR` — This year
- `UNKNOWN` — Unknown

### Closed Lost reasons

- `PRICE` — Price
- `COMPETITOR` — Competitor
- `NO_TECHNICAL_FIT` — No Technical Fit
- `TIMING` — Timing
- `LOST_TO_INTERNAL_BUILD` — Lost to Internal Build

### Closed Hold reasons

- `BUDGET` — Budget deferred
- `TIMING` — Timing deferred
- `CUSTOMER_REQUEST` — Customer requested hold
- `PROCUREMENT_LEGAL` — Procurement/legal delay
- `RESOURCE_CONSTRAINT` — Customer resource constraint
- `INTERNAL_CAPACITY` — Infoshare capacity constraint
- `OTHER` — Other

### Deal stage required fields

These implement the architecture's default gates and remain admin-editable:

- `NEW`: title, owner, exactly one source Lead or Account, and deal type.
- `DISCOVERY`: a note on the requirements and needs gathered.
- `QUALIFIED`: amount and expected close date. Budget, Authority, Need, and
  Timeline stay optional.
- `TECHNICAL_EVALUATION`: POC or trial start date, technical stakeholder
  name, and a success-criteria note.
- `PROPOSAL`: proposal amount, expected close date, and a note that the
  proposal was sent.
- `NEGOTIATION`: a note on terms or redlines, and the expected close date.
- `CLOSING`: a sign-off note and the expected close date.
- `CLOSED_WON`: Won outcome, final amount, and the actual close date. Wins
  are counted on that date, not the day the stage changed.
- `CLOSED_LOST`: Lost outcome and a loss reason from Price, Competitor, No
  Technical Fit, Timing, or Lost to Internal Build.
- `CLOSED_HOLD`: Hold outcome and hold reason. Reopening needs a reason.

## Roadmap clarifications and improvisations

### C-001 — Consistent phase references

- **Change:** Replace the implementation note's stray “M4” and “M7” wording in
  derived plans with the actual Phase 6 access-control and Phase 9
  restore/security gates.
- **Reason:** The specification defines phases, not M-numbered milestones, and
  the mismatched references could permit production data too early.
- **Architecture file:** Preserved unchanged; clarification applies to delivery
  documents.

### C-002 — Consistent Deal terminology

- **Change:** Use `Deal` in implementation artifacts; treat “opportunity” in
  roadmap prose as the same entity, not a second model.
- **Reason:** The data model and API define `Deal`.
- **Affected phases:** 2–10

### C-003 — CSV before XLSX

- **Change:** Phase 8 gates CSV behavior before adding XLSX.
- **Reason:** Narrows failure analysis while preserving the required Phase 1
  import formats by the end of Phase 8.
- **Affected phase:** 8

### C-004 — Explicit percentage formula

- **Change:** Use gate-item counts instead of subjective completion estimates.
- **Reason:** Makes progress auditable and prevents partially coded screens from
  being reported as complete.
- **Affected phases:** 0–9

### C-005 — MVP boundary

- **Change:** MVP completion is Phases 0–9. Phase 10 is not included in the MVP
  percentage or release gate.
- **Reason:** The architecture labels Phase 10 as later modules and requires
  independent scope.

## Open decisions and trigger points

These are not current Phase 0 blockers unless stated:

- **Phase 1:** Select production email delivery and alert ownership before
  enabling password-reset email; provide a logo if required.
- **Phase 4:** Confirm reminder delivery channel if it expands beyond in-app
  batching.
- **Phase 9:** Select provider, managed MySQL service, backup target, secret
  store, alert/incident owners, pilot group, and production data policies.
- **Phase 10:** Prioritize modules and confirm Microsoft tenant/licensing policy
  only after pilot review.

## Change-entry template

```text
### D/C-NNN — Short title
- Date/status:
- Decision or change:
- Rationale:
- Affected phases/files:
- Specification impact:
- Approval source:
- Migration/rollback impact:
```
