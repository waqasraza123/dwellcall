# DwellCall project state

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
