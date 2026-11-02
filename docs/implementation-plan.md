# DwellCall implementation plan

## Standing approach

Target 80% reuse of applicable HVACLine application code and 20% new development.
Inspect the original equivalent and dependencies before each module; adapt working
implementations and record actual reuse in `reuse-inventory.md`. Do not inflate
reuse with irrelevant code, generated files, dependencies or test scaffolding.
Preserve HVACLine and DwellCall's independent history, credentials, database and
hosting. Every unexecuted change remains **UNVERIFIED**.

## Milestones

| Phase | Work and acceptance |
| --- | --- |
| 1 — Foundation | Adapt HVACLine FastAPI/settings/errors/Neon/security. Add the minimum Retell Custom LLM adapter and rental graph. Current source is published but UNVERIFIED. Exit: owner reports working private Test Audio with three fictional rentals, authentication/identity, interruption and duration/admission acceptance. See `phase-1.md`. |
| 2 — Conversation, implementation UNVERIFIED | Existing graph/catalog extended to Renting, Buying and Luxury, call-local requirement revisions, readback confirmation, comparisons, objections and natural closing. Configurable identity/catalog/location; no extra service or database migration. Owner checks and limitations: `phase-2.md`. |
| Optional CRM — implementation UNVERIFIED | The owner subsequently requested implementation before core acceptance was reported. Provider interface/no-op/FUB adapter, durable export workflow and executable mocked specifications are now written using the inspected source patterns. Keep real synchronization disabled until core acceptance, separate owner approval, automation validation and explicit permission for each confirmed snapshot. CRM does not block standalone voice or other phases. See `crm-setup.md`. |
| 3 — Outbound | Adapt HVACLine's consent, allowlists, quota reservations, idempotency, recovery, concurrency, webhook deduplication, unknown outcomes and operator controls. Replace provider-specific calling with Retell. Optional future authorized Telnyx verification and fixed-destination transfer after explicit caller confirmation. Outbound/transfers stay off pending separately approved live acceptance. |
| 4 — Website | Adapt the existing Next.js layout, CSS, components, outbound form, recovery and API bridge. Ivory/charcoal/bronze, serif headlines and property imagery. AI disclosure, verification and explicit calling consent. Preserve the existing GitHub SVG/header pattern; source publication does not activate calling or CRM. |
| 5 — Release | Backend-only/website setup, JSON catalog/schema, Retell instructions, independent Neon/Render/Vercel configuration and license review before MIT release. Include optional CRM instructions; the default quickstart needs no CRM account, credentials or worker. Owner controls publication/activation. |

CRM is the sole approved extension to the original no-CRM scope. It does not
authorize other CRM platforms, contact scraping, campaigns, messaging, showings,
booking, bidirectional sync or unrelated services.

## Execution and current handoff

Do not run tests, builds, lint/format/type checks, readiness probes, migrations or
other verification commands without specific owner authorization. Do not write to
external APIs, commit, push or deploy without a new applicable authorization.
The owner subsequently authorized committing/pushing the current CRM and Phase 2
source to `main`; that request does not authorize verification or live activation.
Preserve the ignored `.env`; never import HVACLine secrets or historical notes.

Next: owner executes/reports core acceptance and checks in `phase-2.md` and `crm-setup.md`.
CRM source and executable mock specifications remain UNVERIFIED; the new migration
is unapplied. No real connection, worker schedule or live synchronization is active.
