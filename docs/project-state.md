# DwellCall project state

## Quantrift-derived Stripe pricing source — 2026-11-05 — UNVERIFIED

Owner authorizes committing and pushing the pricing/billing source, specifications
and setup guide to `main`. Verification, migrations, services, provider changes
and deployment remain outside this publication request.

- Owner requested local Quantrift Stripe pricing. Adapted Free/$0, Pro/$29 and
  Team/$79 monthly USD pricing, Checkout/customer portal, signed webhook receipts
  and bounded reconciliation to existing DwellCall accounts and Neon. Source
  checkout read-only; no credentials, customer data or provider IDs copied.
- Account-specific billing requires existing MFA and approved operator access;
  payment never grants roles, changes quotas or enables providers. Team seats,
  tenant memberships, credit metering and plan paywalls are outside this step.
- New migration 20261105_0011 and Stripe 16.1.0 dependency remain unapplied/
  uninstalled. Billing is disabled by default; existing environment files kept.
  Source and compatibility are UNVERIFIED. No checks, services, migrations,
  provider requests/changes, publication or deployment ran.
- Owner setup/recovery commands and unexecuted specifications: docs/billing.md.

## Account authentication source — 2026-11-05 — UNVERIFIED

Owner authorizes committing and pushing the authentication source, specifications
and setup documentation to `main`. Checks, migrations, services and deployment
remain outside this publication request.

- Owner requested local HVACLine authentication adapted to existing DwellCall Neon.
  Source includes email/password signup/login, mandatory authenticator MFA,
  replacement recovery, persisted throttles, revocable sessions and server bridge.
  HVACLine remained read-only; no accounts/secrets/database contents were copied.
- New migration `20261105_0010` is unapplied. New accounts have no workspace
  privilege until deliberate owner approval by account UUID. Existing shared
  operator-password cookies are superseded by database-backed MFA sessions.
- Source, migrations, dependency compatibility and UI behavior remain UNVERIFIED.
  No checks, installs, migrations, connections, services or publication ran.
  Owner configuration, exact commands, approval SQL and checks: `docs/authentication.md`.

## Publication authorization — 2026-11-04

Owner authorizes committing and pushing all pending outbound fixes, hero voice/text
chat, permanent AI-only policy, specifications and setup guides to `main`.
Implementation remains UNVERIFIED. This does not authorize checks, migrations,
services, provider/account changes, paid calls or deployment commands.

## Permanent AI-only operation — 2026-11-04

Owner explicitly requires human transfers to remain disabled permanently.
DwellCall is an AI-native voice platform operated only by AI agents. Human
requests must receive that plain explanation, without a human connection,
callback, escalation promise or transfer confirmation. This supersedes earlier
notes describing future transfer prerequisites. Implementation remains UNVERIFIED.

## Hero conversation feature — 2026-11-04 — UNVERIFIED

Owner requests HVACLine-derived voice/text chat in the homepage hero with a new
visual style. Preserve the existing operator access and shared conversation limits;
keep live browser flags disabled until owner setup/acceptance. Source includes
browser admission migration 0009; it has not been applied. HVACLine stays read-only.
Owner configuration and commands: `docs/browser-conversations.md`.

## Outbound completion constraints — 2026-11-04 — UNVERIFIED

Owner restricts outbound calling to US destinations and requires transfer to stay
disabled. This turn permits source fixes/specifications only: no verification,
services, migrations, provider/account changes, calls, commits or publication.
Owner validation and required environment names: `docs/outbound-calling.md`.

## Retell + Telnyx outbound source — 2026-11-04 — UNVERIFIED

Owner now authorizes committing and pushing all pending outbound source, focused
specifications, setup documentation and the product README/logos to `main`.
This does not authorize checks, migrations, services, provider activation or calls.

- Owner authorizes private, consented, allowlisted demonstration calling source.
  Adapted HVACLine's outbound reservations/recovery/preflight/frontend patterns;
  HVACLine remained read-only. Retell is the sole originator; no Telnyx dialing API.
- New migration `20261104_0008` adds hashed call/events/suppression evidence and
  emergency flags on the existing audio guard. Shared admission/spending, pinned
  phone identities, webhook lifecycle, lookup/binding, conservative unknown handling
  and operator carrier-completion recovery are implemented in source.
- Phone WebSockets reuse the existing consultant, spoken transcript and streaming
  cancellation. Human transfer is permanently disabled by owner decision; legacy
  carrier evidence remains available for conservative recovery only.
- Existing Next.js workspace adds `/calls`, authenticated controls/history/recovery
  and explicit development simulation without provider calls. Discovery never dials;
  GHL, FUB and HubSpot paths remain present.
- No checks, installs, migrations, services, live calls/config changes, credential
  edits or publication ran. Owner setup/commands: `docs/outbound-calling.md`.

## Current mission — 2026-11-03

The owner replaced the voice-first roadmap with **DwellCall — AI Real Estate Lead
Intelligence**. The owner now authorizes Phase 2 implementation. GoHighLevel is
the primary listing-agent CRM; Follow Up Boss and Retell remain optional, disabled by default. No autonomous
outreach. The 80% applicable-code reuse goal remains a target, not a measured result.

## Phase 1 source delivered — UNVERIFIED

- Existing FastAPI/configuration/errors/Neon/SQLAlchemy/security/job-budget code is
  reused. HVACLine equivalents were inspected read-only; no source checkout edits.
- New source defines source permission registry, import runs, listing observations/
  revisions, agent identities, many-to-many relationships, contact provenance,
  review decisions and minimal audit evidence. Migrations `20261103_0003` and
  `20261103_0004` are unapplied.
- Synthetic CSV/JSON provider, bounded local CLI and authenticated operator APIs
  implement normalization, replay protection, deterministic deduplication/updates,
  global transaction locking, daily admission limits and persisted run/checkpoint
  evidence. No LLM/provider HTTP requests are part of ingestion.
- Stable listing/agent IDs and approved authority evidence govern matches.
  Address-only and conflicting identities require review. Office phones/names
  cannot merge people. Missing fields/contacts remain unknown. Demo verification
  is labeled synthetic and never presented as actual verification.
- Permissions, role masking, retention-aware reads, suppression and bounded
  owner-run deletion are implemented in source. Weak agents remain local with no
  contact activation until explicit evidence-scoped review. Durable local/strong
  identity and suppression-only alias hashes survive purge and reimports; they
  cannot authorize merges or unsuppression. Runtime acceptance is pending.
- Admin-only review inspection/immutable approval/rejection reuse existing API
  authorization, Neon transactions and ingestion/row locks. New-UUID reimport
  applies approved scoped associations without reassigning global IDs. Audit and
  decision evidence persist; source-retention cleanup redacts review payloads.
  Synthetic/weak/unresolved identities remain ineligible. Phase 2 adds live-agent
  eligibility checks and gated durable dispatch below.
- Optional voice imports are lazy behind its existing disabled flag. FUB remains
  consultation-only. `CRM_PROVIDER=none|gohighlevel|followupboss`, default none;
  optional approved GHL auto-queue reserves live-agent jobs during imports.
- Synthetic examples and unexecuted unit/API/isolated-PostgreSQL specifications
  are written. Exact owner commands and limitations: `docs/listing-ingestion.md`.

No tests/builds/lint/format/type checks, verification, installs, migrations,
connections/imports, services, provider writes/configuration, commits/pushes or
deployments were executed for this step. Existing `.env` is preserved; the owner
reports URLs already supplied. All runtime/migration/compatibility behavior remains
**UNVERIFIED** pending owner results.

## Deferred

Phase 3: actual authorized feed connectors, structured AI where useful, broader
identity repair, permitted enrichment and bounded scheduling/checkpoints/backoff.
Phase 4: adapt HVACLine's actual Next.js frontend; DwellCall has no web app yet.
Phase 5: owner acceptance, source/privacy/license review and independent release.
Portal APIs/MLS/RESO are not integrated or operational. Poll settings are inactive.
No outreach, paid resources or external acceptance is inferred.

## Existing source history and restrictions

Earlier owner-authorized source publications: `a5ec75d`, `de121d4`, `4cf913f`,
`afde1e3` on `main`. Earlier consultant/CRM behavior remains UNVERIFIED. That
publication approval does not authorize publishing this new product work.
Codex must not execute verification/services/migrations or publish/activate without
the owner's specific applicable instruction. Preserve independent Neon/credentials/
hosting and HVACLine. Detailed actual reuse: `docs/reuse-inventory.md`.

## Phase 2 source delivered — UNVERIFIED

- GHL API v2 PIT/location adapter: conservative contact search/create/update,
  additive tags, owned fields, property/source references and optional qualified
  opportunities. Existing unowned matches require explicit operator binding.
- Agent-specific mappings/jobs/audits (unapplied revision 0005) reuse existing
  Neon/session/locking/budget/client/worker CLI. Reservations commit before HTTP;
  uncertain writes require lookup, with no blind creation replay. Throttle/auth
  pause/attempt fencing/recovery and retained mapping evidence persist.
- Admin APIs expose setup/read-scope discovery, eligibility preview, queue/history/
  audits, bounded processing, safe retries, reconciliation and contact binding.
  Existing field mappings are discovered/validated; setup creates no remote fields.
  Optional location creation requires agency scope, owner/plan attestation and a
  durable pre-call reservation; uncertain provisioning is never auto-retried.
- Permission-scoped local live file imports now accept explicit synthetic=false
  separately from synthetic sources; no feed connector or verifier was added.
  Synthetic, weak, suppressed, shared/unverified contacts and unresolved/rejected
  reviews cannot export. Send-time checks serialize with identity/source changes.
- Default gates remain off; no environment/credential edits, live provider calls,
  tests/checks/services/migrations/publication executed. Mocked and isolated-DB
  specifications are written, not run. Commands/operational limits: docs/gohighlevel.md.

The owner explicitly authorized committing and pushing the pending Phase 1/2
source to `main`. This publication does not authorize checks, migrations, services,
live CRM activation or deployment; implementation remains UNVERIFIED.

## Phase 4 source delivered — UNVERIFIED

- Added HVACLine-derived Next.js application shell, operator session/allowlisted server bridge, dashboard, listings/details/history, agent directory/provenance, discovery/jobs/history, reviews, CRM controls and activity.
- Backend additions reuse existing permission-aware queries, ingestion, review/suppression and GHL services. New migration `20261103_0006` adds durable discovery jobs/attempts and action reservations; unapplied.
- Bundled synthetic discovery works through deliberate source setup/job/run actions. Optional bounded demo polling CLI is written; no scheduler is configured or started. Live feeds and AI enrichment remain absent.
- CRM location/credentials/opportunity configuration remains owner-managed on the backend. UI validates existing field mapping and exposes deliberate queue/dispatch/recovery actions without credentials.
- No checks, installs, services, migrations, live calls or publication were executed. Runtime, security, responsive layout and owner acceptance remain unverified. Commands: `docs/phase-4.md`.

The owner authorized pushing Phase 4 and merging it into `main`. Publication does not authorize checks, migrations, services, deployment or live CRM activation. Implementation remains UNVERIFIED.

## HubSpot source extension — UNVERIFIED

- Owner requested implementation on a new local branch without publication. `feat/hubspot-crm` is based on existing main `ebf6e10`; no new commits or remote branch were created.
- Adds the optional `hubspot` provider, Service Key/private-app configuration, date-versioned adapter, owned contact/company properties and optional deal associations. Existing agent contracts/jobs/worker/eligibility/locks/audits and frontend controls are extended rather than replaced.
- Migration `20261104_0007` adds company references to existing CRM links; unapplied. Unknown writes remain lookup-gated; source permissions and synthetic/suppression exclusions remain authoritative. GHL/FUB and optional Retell paths remain present.
- Mocked and isolated-database specifications are written, not executed. No checks, installs, services, live CRM calls, account changes, publication or deployment ran. Owner setup and exact commands: `docs/hubspot.md`.

- Publication authorized by owner: publish `feat/hubspot-crm` and merge into `main`. Implementation remains UNVERIFIED; no checks, migrations, services or live CRM calls executed.
