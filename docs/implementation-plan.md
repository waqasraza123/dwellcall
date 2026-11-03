# Real estate lead intelligence implementation plan

This plan supersedes the voice-first roadmap. Retell/LangGraph and optional Follow
Up Boss are preserved, disabled by default. No autonomous outreach is in scope.
Reuse applicable DwellCall/HVACLine code first; target 80% where practical, with
actual file treatment recorded rather than unsupported percentages. Never modify
HVACLine or copy secrets, unrelated functionality or hosting identifiers.

| Phase | Scope and acceptance |
| --- | --- |
| 1 — Foundation, source UNVERIFIED | Reuse FastAPI/Neon/security/job foundations. Add listing/agent schema, permissions, provider contracts, synthetic CSV/JSON ingestion, deterministic deduplication, provenance, relationship history, authenticated scoped review decisions, suppression persistence and unexecuted specifications. Owner accepts repeat imports/updates and identities in isolated PostgreSQL. |
| 2 — GoHighLevel source UNVERIFIED | Extend existing CRM abstraction to `none|gohighlevel|followupboss`; GHL becomes the product default with dispatch still gated. Official API v2 private token, location/provisioning boundary, safe contact upsert, custom fields, additive tags/source, property references, qualified opportunities, durable dispatch, throttling and uncertain-write reconciliation. Mocks/isolated DB before separately approved live writes. |
| 3 — Intelligence and sources | Documented licensed connectors after rights/credentials; permission-scoped enrichment, structured AI for ambiguous work, broader identity repair, bounded scheduling/backoff and incremental checkpoints. Portal names remain unavailable until authorized implementation and acceptance. No scraping or invented contacts. |
| 4 — Frontend/reporting | Adapt HVACLine Next.js components/CSS/layout/API bridges into premium authenticated overview, listings, agents, discovery, integrations and activity. Actual counts, synthetic labels, contact masking and existing GitHub icon pattern. Dashboard notifications first. |
| 5 — Release/acceptance | Owner-run end-to-end, restart/recovery, licensing/privacy and GHL acceptance; independent deployment guides. Owner controls paid provisioning, publication and scheduled activation. Optional external notifications stay off. |

Phase 1 implements a synthetic file provider and licensed-feed contract only.
No licensed connector, polling worker, AI enrichment or website is delivered.
Phase 2 GHL source and permission-scoped live file intake are implemented; see
[gated GHL owner workflow](gohighlevel.md). Poll frequency is inactive registry metadata. The CRM job
pipeline is retained for Phase 2; ingestion never enqueues consultation exports; approved GHL auto-queue uses agent jobs.

Source permissions separately record retrieval, storage, display, contacts,
verification trust, export, geography, attribution and retention. Access to public
business contacts is not outreach consent. No campaigns/messages/showings/calls.

Every implementation change remains **UNVERIFIED** pending owner results. Codex
must not execute tests/builds/lint/format/type checks, verification, migrations or
services. No commit/push/deploy, provider changes, paid resources or external writes
without explicit applicable authorization. Earlier publication approval does not
authorize publishing this new work. Exact commands: [ingestion guide](listing-ingestion.md).
