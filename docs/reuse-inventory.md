# Phase 1 reuse inventory — UNVERIFIED

Source: local `/Users/mc/development/hvacline`, corresponding to
`waqasraza123/hvacline`. Source inspection and selective extraction only; HVACLine
was not modified. Destinations below are relative to this repository.
`backend/` abbreviates `apps/backend/src/dwellcall/`; original backend paths start
with `apps/backend/src/insurance_operations/`.

| HVACLine source | DwellCall destination | Treatment and reason |
| --- | --- | --- |
| `application.py` | `backend/application.py` | Adapted factory, sessionmaker, lifespan, CORS, correlation IDs, validation/error handlers, health/readiness. Removed HVAC, booking, identity, portal and provider routes. |
| `api.py` | `backend/api.py` | Adapted initialization; removed inbound telephony and WhatsApp setup. |
| `settings.py` | `backend/settings.py` | Copied PostgreSQL settings, test-target isolation and Neon pooler normalization; retained origin validation. Added private Retell/business configuration; removed unrelated settings. |
| `errors.py` | `backend/errors.py` | Copied structured errors and correlation response without behavioral replacement. |
| `database/connection.py` | `backend/database/connection.py` | Copied engine, pooling, direct migration URL, psycopg conversion and readiness; renamed namespace/application name. |
| `database/models/base.py` | `backend/database/models/base.py` | Copied SQLAlchemy foundation and naming convention. No historical application models imported. |
| `demo_security.py`; strict `telephony/outbound/routes.py` admin dependency | `backend/admin_security.py` | Adapted constant-time authorization. Removed the general sandbox bypass; operator authorization is always mandatory. |
| `telephony/webhook_validation.py` | `backend/telephony/webhook_validation.py` | Copied bounded, value-free diagnostic redaction; added Retell field names. This file handles diagnostics, not signature verification. |
| `telephony/outbound/service.py`; `conversations/service.py` | `backend/telephony/retell/service.py` | Adapted transaction/guard-row locking, active/unknown blocking, daily counting, durable identity and monotonic finalization for private web sessions. Replaced agency ownership with one independent admission guard; no outbound workflow imported. New cost reservation is DwellCall code. |
| `conversations/local_session.py` | `backend/consultant/graph.py`, `backend/consultant/catalog.py` | Inspected extraction, transcript bounds and draft patterns. New implementation: HVAC intake/Ollama/speech contracts do not supply Retell streaming, LangGraph or rental matching. Pattern references do not count as copied lines. |
| `telephony/providers/elevenlabs.py`; `telephony/outbound/provider.py` | `backend/telephony/retell/provider.py`, `schemas.py`, `routes.py` | Inspected provider, signing, body bounds and identity patterns. New Retell adapter uses the supported SDK/protocol; ElevenLabs wire formats cannot be reused. No ElevenLabs provider copied. |
| No property-catalog equivalent (backend searched for rental/property catalog) | `data/properties.json`, `backend/consultant/catalog.py` | New fictional rental catalog and deterministic filters. |
| `migrations/env.py`, `migrations/script.py.mako`, `alembic.ini` | Same paths | Copied runner/template/configuration; package renamed. No historical revision copied. |
| Existing model/migration conventions | `backend/database/models/audio_session.py`; `migrations/versions/20261103_0001_private_audio.py` | New minimal guard/session schema and independent root revision, not an HVAC schema clone. |
| `pyproject.toml`, `.gitignore`, `AGENTS.md` | Same paths | Adapted packaging/dependencies, preserved ignore rules and working agreement. Configuration/scaffolding excluded from code-reuse credit. |
| `tests/test_api.py`; `tests/database/test_connection_settings.py` | `tests/test_api.py`; `tests/test_connection_settings.py` | Adapted existing liveness/readiness and database configuration specifications. Test code excluded from application-reuse credit. |
| `tests/database/conftest.py` | `tests/database/test_audio_admission.py` | Inspected first; replaced fixture because source downgrades/truncates shared tables. New opt-in specifications create/drop only a unique test schema on an isolated test target. |

## Deferred equivalents — inspect again before implementation

| Existing HVACLine source | DwellCall decision |
| --- | --- |
| `telephony/outbound/{service,routes,settings,schemas}.py` and outbound model | Phase 3: retain consent, allowlist, quota/idempotency reservation, recovery, unknown outcomes and operator controls; adapt provider-specific calls to Retell. Do not import unrelated agency infrastructure. |
| `apps/web/src/app/{page.tsx,layout.tsx,product.css,styles.css}` | Phase 4: adapt the existing application; no frontend scaffold created in Phase 1. |
| `apps/web/src/components/{brand.tsx,product-icons.tsx}` | Phase 4: retain useful components, GitHub SVG and header placement. Source header/brand inspected. Link must remain hidden until publication approval. |
| `apps/web/src/features/outbound-demo/`, `apps/web/src/app/api/outbound-demo/route.ts` | Phase 4: adapt existing form/status/server bridge after Phase 3; inspect full dependency tree then. |

## Actual extraction evidence

Three complete runtime foundation files (`errors.py`, `database/connection.py`,
`database/models/base.py`) were extracted, plus the complete webhook diagnostic
helper before its field-name adaptation: **249 original source lines across four
files**, before changes. Selective source blocks were also extracted from
`settings.py`, `application.py` and `api.py`. Admin authorization and private
session admission adapt the inspected original algorithms and working patterns.
These nine runtime destination modules have source reuse; the Retell protocol,
adapter/router, graph, rental catalog and minimal session models are new.

No application-wide reuse percentage is claimed. Module counts and source-block
line counts are not an 80% reuse measurement. The large existing website and
outbound workflow are intentionally absent from this milestone. A later measured
report must compare retained applicable source lines with the final application,
excluding dependencies, generated artifacts, tests, scaffolding and irrelevant
copied code. Source reuse is not a claim of verified behavior or license clearance.

## Optional CRM implementation — UNVERIFIED

The owner subsequently requested implementation while core voice acceptance is
pending. Real sync stays disabled. These original equivalents were inspected
without modifying HVACLine; paths below distinguish source reuse from new code:

| Original source | Actual DwellCall destination and treatment |
| --- | --- |
| `conversations/contracts.py` | `backend/crm/contracts.py`: adapt provider protocol and typed immutable metadata/result pattern. |
| `conversations/service.py::confirm_intake`; `leads/{schemas,service}.py`; `database/models/lead.py` | Minimal confirmed consultation/lead snapshot and `backend/crm/service.py`: reuse validation, transaction, summary, ownership and row-version patterns. Remove booking/HVAC/agency dependencies. |
| `customer_memory/service.py` consent and summary sections | Confirmation/export consent and bounded authorized-summary patterns; no memory-product copy and no reuse of memory permission as CRM permission. |
| `database/models/operations.py`; intake/lead replay helpers | Local export unique scope, fingerprint, conflict/replay and audit patterns; adapt to independent minimal models. |
| `notifications/booking.py`; `database/models/booking_integrations.py`; `booking_jobs.py`; `worker.py`; `job_execution.py` | `backend/crm/jobs.py` and minimal durable export rows: adapt enqueue, bounded processing, locks and deadlines. Replace provider-specific retry assumptions with FUB-safe unknown-result handling. |
| Already adapted DwellCall foundation | Reuse settings, FastAPI/API errors, operator authorization and Neon connection/model base directly. |
| No HVACLine native CRM/FUB module found | New `backend/crm/providers/{none,followupboss}.py`; FUB authentication/event mapping and typed delivery states need provider-specific code. |

| Additional source | Actual extraction |
| --- | --- |
| `job_execution.py` | Copied the complete runtime module to `backend/crm/job_execution.py`; changed namespace/service name and disabled environment proxy inheritance/redirects in clients. Deadlines, transport budgeting, statement limits and bounded engine configuration were retained. |
| `notifications/booking.py`, `booking_jobs.py`, `worker.py` | Adapted enqueue/job-batch/advisory-lock/deadline/CLI structure into `backend/crm/{service,jobs}.py`. FUB ambiguity, fencing and cross-batch rate-delay rules are new. No calendar/email/HVAC workflow copied. |
| Existing DwellCall database fixture | Moved to `tests/database/conftest.py`, added CRM dispatch-state initialization and reused for new concurrency/workflow specifications. Test code receives no application-reuse credit. |

Confirmed-snapshot fields and consent scope, CRM models/migration, provider mapping,
mocked specifications and sample payload are new domain-specific implementation.
Lead/memory source supplied validation/confirmation/retention patterns rather than
copied products or unused tables. `docs/crm-setup.md` records setup and owner checks.
The earlier Phase 1 extraction evidence is unchanged; no 80% or other
application-wide percentage is claimed. All new behavior remains UNVERIFIED.

## Phase 2 conversation extension — UNVERIFIED

| Inspected source | DwellCall treatment |
| --- | --- |
| Existing DwellCall `consultant/catalog.py`, `consultant/graph.py` and Retell router | Adapted in place: scenario-aware prices/filters, comparisons, objection context, call-local revision state and completion/end-call handling. The working graph structure, clients, streaming, authentication and admission remain. Three original rental examples are retained. |
| HVACLine `conversations/spoken.py` | Copied/adapted its generic `SpokenTurn`, `normalized_speech` and `require_spoken_confirmation` implementation to `backend/consultant/spoken.py`. Changed role/content names, requirement-specific action wording and Unicode token preservation. Excluded the HVAC-specific readback builder; the new property readback includes all current fields and its revision. |
| HVACLine `conversations/local_session.py` extraction/draft/merge and `conversations/schemas.py` confirmation patterns | Adapted into existing extraction and new `backend/consultant/state.py`. Full snapshots replace the HVAC merge's ignore-null/sticky-hazard behavior because property preferences can be explicitly withdrawn. Only completed streams commit a candidate revision. No HVAC contact/intake fields copied. |
| HVACLine `leads/service.py` row-version and confirmed-intake patterns | Adapted revision invalidation and current-readback confirmation concepts to one WebSocket's state. No agency/customer database model copied; no new persistence without storage permission. |
| Existing DwellCall CRM snapshot schema | Reused for compatibility specifications. The confirmed property summary helper omits contacts and all permissions; no automatic CRM authorization/network bridge was added. |

New property scenarios/readback content and fictional purchase/luxury records are
domain-specific additions. Mocked specifications/documentation are excluded from
reuse credit. Actual reuse is recorded by source/destination/treatment; 80% remains
a product target, not a measured result for these early AI-heavy phases.
