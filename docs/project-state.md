# DwellCall project state

## Phase 2 source implementation — UNVERIFIED — 2026-11-03

The owner explicitly requested implementation plus commit/push to `main`. Existing
CRM source was published first as `4cf913f`; GitHub accepted `de121d4..4cf913f`
without force. This authorization also covers publication of the Phase 2 source.
It does not authorize verification, migrations, services, provider edits or activation.

Existing graph/catalog/router source is extended in place for Renting, Buying and
Luxury; the three original rentals remain alongside four fictional purchase/luxury
examples. One configurable consultant uses deterministic scenario/budget/feature
filters, comparison mismatch flags and objection/follow-up context. Call-local
revision state invalidates prior confirmation on corrections. Adapted HVACLine's
actual generic spoken-confirmation helper, with current full readbacks and separate
caller replies. Stream cancellation does not commit unfinished candidate state.
Explicit closing phrases bypass the LLM and set the final Retell end-call flag.

Confirmed summary preparation omits contacts and storage/CRM permission. State stays
in memory per socket; there is no new transcript/summary archive, database migration
or automatic export bridge. Human transfer remains unavailable. All real activation
and the existing admission/duration limits remain unchanged.

New/updated specifications cover scenario matching, comparisons, configurable data,
state isolation, cancellation, current/stale/partial readback and closing. None ran.
No installs, checks, migrations, services, live model/Retell/FUB activity or deployment
commands ran. `.env`, ignored local notes and HVACLine are excluded from publication.
Runtime behavior remains UNVERIFIED. Exact owner checks: `docs/phase-2.md`;
CRM setup remains `docs/crm-setup.md`. Source reuse is recorded without a percentage.

## Optional CRM source implemented — UNVERIFIED — 2026-11-03

The owner subsequently instructed “proceed to implementation.” Source now includes
an optional typed provider/no-op/FUB adapter, confirmed snapshot/permission API,
durable Neon export workflow, bounded worker, operator reconciliation and mocked
unit/database specifications. Core voice acceptance is still pending. Real sync
remains gated by default `CRM_PROVIDER=none`, sync off, explicit owner/core/automation
attestations and separate caller data/storage permission per confirmed snapshot.

Inspected HVACLine provider/lead/confirmation/summary/consent/idempotency/job
implementations before adaptation. Extracted its complete `job_execution.py` and
retained deadline/engine/transport behavior, with DwellCall namespace and stricter
client defaults. Reused transaction/replay, bounded job/advisory-lock and consent
patterns without copying agency/booking/email products. FUB-specific mapping and
safe uncertain outcomes are new. No unsupported reuse percentage is claimed.

New unapplied revision `20261103_0002` adds CRM export/audit/throttle tables.
The default API does not require them. CRM performs no network work in the live
Retell graph. Only a post-call operator-authorized snapshot can enqueue. Unknown
submissions/crashed sending attempts are held; rate-limit delays and credential
pauses persist, with audited operator resume; old
versions/destinations/withdrawn permissions cannot silently requeue or reroute.
Personal payloads expire through owner-run maintenance; no automatic TTL is claimed.

The real `.env` and HVACLine remain untouched. No installs, tests/builds/verification,
migrations, services, API writes or provider edits ran during implementation.
The later authorized CRM publication is recorded above. Runtime, migration and mocked integration remain UNVERIFIED. Next owner steps:
`docs/crm-setup.md` and core acceptance in `docs/phase-1.md`. No live CRM approval
has been granted. This CRM exception does not authorize unrelated integrations.

## Phase 1 published to main — 2026-11-03 — UNVERIFIED

The owner explicitly requested pushing Phase 1 to `main`. Initial independent
source commit `a5ec75d` was accepted as a new `origin/main` branch in the public
`waqasraza123/dwellcall` repository, without force. Local `main` tracks
`origin/main`. The 44-file commit excludes ignored `.env`, local session notes
and machine artifacts. Git hooks were skipped and the commit requests CI/Render/
Vercel skips. No verification, migration, service, provider configuration, live
conversation or deployment command ran; external automation state is unverified.

Implementation/runtime and private Test Audio acceptance remain **UNVERIFIED**.

## Owner decisions — 2026-11-03

- Start with Phase 1 only, using applicable code from `waqasraza123/hvacline`.
  Preserve HVACLine; keep database, credentials, configuration and eventual Git
  history/hosting independent. Target 80% applicable-code reuse across the product,
  without copying irrelevant code or claiming an unsupported percentage.
- Keep Neon and adapt the existing FastAPI architecture. First milestone: private
  Retell Test Audio with three fictional rentals and one minimal LangGraph agent.
- Phase 2 expands intelligence; Phase 3 adapts existing outbound protections;
  Phase 4 adapts the existing Next.js website. No website rebuild, public callback,
  outbound dialing, SMS, transfer or publishing in Phase 1.
- Preserve one active/unresolved call, <=180 seconds, quotas, consent/allowlists for
  future telephone calling, spending admission and disabled transfers. No RAG,
  vector database, MLS or multi-agent architecture. The optional Follow Up Boss
  exception is scoped above; other CRM work remains excluded.
- Codex must not run verification commands, services, migrations or live tests.
  No commit, push, deployment/provider edits, SMS or paid calls without explicit
  authorization. Owner commands: `docs/phase-1.md`.

## Phase 1 implementation — UNVERIFIED

Selected HVACLine foundation source was extracted and adapted to the `dwellcall`
package. New source contains private Retell web-call authentication/identity,
typed streaming protocol, bounded interruption handling, signed final events,
serialized Neon admission and a minimal graph over three fictional Austin rentals.
Fresh root migration `20261103_0001` is written, unapplied. Private audio defaults
off. The owner reports database URLs supplied in the ignored DwellCall `.env`.
Database connectivity, schema and resource independence remain UNVERIFIED;
no database connection or provider provisioning was performed by Codex.

All implementation/runtime behavior, dependencies, automated specifications and
the first Test Audio conversation remain **UNVERIFIED**. Source inventory and
actual extraction evidence: `docs/reuse-inventory.md`. No 80% claim is made.
No source credentials, private notes, Git history or hosting identifiers were
copied; no license grant is asserted. Source publication is recorded above;
next handoff is owner dependency/check/schema/provider setup and private audio
acceptance.
