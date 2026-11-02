# DwellCall project state

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
  vector database, MLS/CRM or multi-agent architecture.
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
