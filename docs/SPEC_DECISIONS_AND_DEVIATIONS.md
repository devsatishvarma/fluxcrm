# FluxCRM Specification Decisions and Deviations

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
  should become `fluxcrm` is a Phase 0 design decision and must not be changed
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
  `fluxcrm`.
- Use `fluxcrm` as the Django project/settings package and keep the architecture
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
  proved the list query count does not grow with the rows on the page.
- Seed and API keys use this document's uppercase taxonomy. The architecture
  sample's lowercase source names are illustrative only.
- **Affected phases:** 2, 3, 5, 6, and 9
- **Specification impact:** Preserves the Phase 2 exit gate that a Deal cannot
  be orphaned or attached to an Account yet.
- **Approval source:** Phase 2 delivery plan.

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
- `PROFESSIONAL_SERVICES` — Professional Services
- `HEALTHCARE` — Healthcare
- `FINANCIAL_SERVICES` — Financial Services
- `MANUFACTURING` — Manufacturing
- `RETAIL` — Retail
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
- `OTHER` — Other

### Disqualification reasons

- `BAD_DATA` — Invalid or unusable data
- `DUPLICATE` — Duplicate record
- `NO_FIT` — Outside ideal customer profile
- `NO_NEED` — No relevant need
- `NO_AUTHORITY` — No access to authority
- `NO_BUDGET` — No viable budget
- `OUTSIDE_TERRITORY` — Outside served territory
- `OTHER` — Other

### Closed Lost reasons

- `PRICE` — Price
- `COMPETITOR` — Competitor selected
- `NO_DECISION` — No decision
- `BUDGET` — Budget unavailable
- `TIMING` — Timing
- `REQUIREMENTS_GAP` — Requirements gap
- `RELATIONSHIP` — Relationship/incumbent
- `INTERNAL_CANCELLED` — Internally cancelled
- `OTHER` — Other

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
- `CONTACTED`: logged contact attempt or a next task.
- `QUALIFIED`: amount/currency; expected close date or target quarter; Need not
  Unknown; Authority at least Partial.
- `DISCOVERY`: primary contact, or explicit not-yet-identified reason;
  discovery activity; all BANT statuses reviewed.
- `PROPOSAL`: proposal amount, expected close date, and proposal-sent
  activity/date.
- `NEGOTIATION`: decision process and next step; competitor when known.
- `CLOSING`: close plan, confirmed target close date, and latest next task due
  date.
- `CLOSED_WON`: Won outcome, final amount, and close date.
- `CLOSED_LOST`: Lost outcome and loss reason.
- `CLOSED_HOLD`: Hold outcome and hold reason; revisit date remains optional.

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
