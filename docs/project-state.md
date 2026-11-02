# DwellCall project state

## Main publication authorized — 2026-11-03 — UNVERIFIED

The owner explicitly requested pushing Phase 1 to `main`. The independent local
repository is on an unborn `main` branch; origin is `waqasraza123/dwellcall`, whose
remote repository is public and empty at inspection. Prepare the initial source
commit and push without force. Exclude ignored `.env`, local session notes and
machine artifacts. Skip local Git hooks and request CI/deployment skips to honor
the standing no-verification/no-deployment instruction. No provider configuration,
migration, service or live conversation is authorized by publication.

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

## Local implementation — UNVERIFIED

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
copied; no license grant or publication is asserted. Next handoff is owner
dependency/check/schema/provider setup and private audio acceptance.
