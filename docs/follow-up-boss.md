# Optional Follow Up Boss integration — implementation UNVERIFIED

The owner subsequently requested implementation. The provider adapter, durable
workflow and executable mocked specifications are now written, unexecuted. Core
Retell/LangGraph acceptance remains pending; real dispatch stays disabled. This
source does not grant permission to export personal information. Exact owner setup
and checks: [crm-setup.md](crm-setup.md).

## Provider interface and reuse

Use a narrow typed `CrmProvider` protocol following HVACLine's existing provider
contracts: an immutable confirmed-consultation export goes in; a typed delivery
receipt, retryable rejection, permanent failure, ignored source or uncertain outcome
comes back. The provider handles authentication, event mapping and response
classification. The service owns consent, persistence, deduplication and scheduling.
`NoCrmProvider` performs no I/O and reports disabled, never delivered.
`FollowUpBossProvider` is the first real provider. Do not add a generic CRM platform.

Source destinations: `dwellcall/crm/{contracts,settings,service,jobs,routes}.py`,
`crm/providers/{none,followupboss}.py` and minimal confirmation/export models.
The following HVACLine equivalents were inspected and adapted:

| HVACLine source | Adaptation |
| --- | --- |
| `conversations/contracts.py` | Provider protocol, immutable metadata/receipt pattern and close lifecycle. |
| `conversations/service.py::confirm_intake`, `conversations/schemas.py` | Owned, confirmed snapshot and transactional intake creation; remove HVAC/booking branches and transcript export. |
| `leads/{schemas,service}.py`, `database/models/lead.py` | Contact validation, bounded summary, row version, ownership/audit and presentation, without HVAC urgency/callback machinery. |
| `customer_memory/service.py` consent/summary sections | Scope, source eligibility, retention/revocation and authorized-summary patterns. Memory/voice consent must never become CRM consent; do not copy the memory product. |
| `database/models/operations.py` and intake/lead replay helpers | Unique request scope, fingerprint, conflict detection and durable result replay; remove unrelated foreign keys. |
| `notifications/booking.py`, `database/models/booking_integrations.py`, `booking_jobs.py`, `worker.py`, `job_execution.py` | Transactional enqueue, durable work, bounded batches, locks and deadlines; remove email/calendar/booking behavior. Resend-specific idempotency headers are not a FUB guarantee. |
| Already adapted DwellCall API/settings/errors/admin security/database | Reuse directly for optional setup, operator authorization, SQLAlchemy persistence and structured errors. |

No native CRM/FUB equivalent was found. Provider mapping and FUB-specific delivery
handling are new; the complete job deadline/connection module was extracted and
adapted. `reuse-inventory.md` distinguishes copied source from adapted patterns;
no application-wide reuse percentage is claimed.

## Configuration and short setup guide

Runtime configuration is declared in `crm/settings.py`. The complete disabled
sample is in `.env.example`; the owner's ignored `.env` remains untouched:

```dotenv
CRM_PROVIDER=none
CRM_SYNC_ENABLED=false
CRM_OWNER_APPROVED=false
CRM_CORE_VOICE_VERIFIED=false
CRM_AUTOMATIONS_DISABLED_VERIFIED=false
CRM_HASH_SECRET=
FOLLOWUPBOSS_API_KEY=
FOLLOWUPBOSS_SYSTEM_NAME=
FOLLOWUPBOSS_SYSTEM_KEY=
FOLLOWUPBOSS_LEAD_SOURCE=DwellCall Demo
```

1. Complete core voice acceptance before real synchronization. The adapter and
   mocks are written with CRM disabled; execute checks only under owner control.
2. The owner registers DwellCall as a system and obtains its system name/key. Use
   HTTPS Basic authentication with the FUB account API key as username and an empty
   password; send registered `X-System` and `X-System-Key` headers on every request.
   System identity is separate from account authentication. Follow the official
   [onboarding](https://docs.followupboss.com/docs/start-here-brand-new-integration),
   [authentication](https://docs.followupboss.com/reference/authentication) and
   [identification](https://docs.followupboss.com/reference/identification) rules.
3. Keep keys in backend `SecretStr` environment settings, excluded from browser
   bundles, logs and errors. Pin the HTTPS API origin, disallow redirects and
   implicit HTTP retries. Bind jobs/permissions to the approved destination account;
   changing credentials must not reroute already-authorized personal information.
4. Use an approved isolated demo account/source. Before live writes, establish that
   new and existing-contact inquiry events cannot trigger campaigns, messages,
   action plans or downstream integrations. If this cannot be established, real
   sync stays off. Omission of campaign fields does not disable existing CRM rules.
5. After separate owner approval and validation, select `followupboss` and enable
   `CRM_SYNC_ENABLED`. Obtain separate explicit permission for each confirmed
   data snapshot; configuration and owner activation alone do not authorize export.

`CRM_PROVIDER` must accept only `none|followupboss`, default to `none` and reject
unknown values. `none` requires no credentials, creates no client/jobs and changes
no voice behavior. An enabled FUB provider requires complete registered credentials,
approved destination and owner activation. Sync-off never dispatches. Switching to
`none` suspends queued work; re-enabling rechecks destination/consent/retention and
must not replay unknown outcomes. API-key auth is the initial single-account scope;
official OAuth support is a later, separately authorized multi-account option.

## Confirmed data and inquiry mapping

Persist only a minimal confirmed snapshot independent of the live graph draft:
confirmed name/contact details, scenario (`renting|buying|luxury`), budget with
currency/period, requested location, requirements and a concise bounded consultation
summary. Model-generated summaries require confirmation. Unknown fields are absent.
Require a confirmed email or phone for matching. Never invent contacts, split names
speculatively, use unconfirmed caller ID or export raw transcripts/audio/prompts.

Record explicit permission identifying Follow Up Boss, the business, purpose,
destination, selected fields/snapshot version and timestamp. Keep it separate from
microphone, local retention and phone/SMS permissions and owner integration approval.
Denial, silence, revocation/expiry, an unfinished consultation or an unconfirmed
revision means no export. Minimize stored payloads and apply an owner-approved
bounded retention policy to personal snapshots and pending work.

Use `POST https://api.followupboss.com/v1/events`, `type="General Inquiry"`, the
configured source and registered system. Map confirmed names/contact values into
`person`; put scenario, budget/currency/period, location, requirements and summary
in documented message/description fields, with an opaque export reference for
reconciliation. Do not invent custom fields or map monthly rent to purchase price.
See the [official event contract](https://docs.followupboss.com/reference/events-post).

For fictional properties, clearly label the source/description **FICTIONAL
DEMONSTRATION — no real listing or availability**. Omit the `property` object,
MLS identifiers and purported live listing URLs/addresses/prices. A demo property
name in an approved summary must be labeled fictional. A real person's information
still requires separate permission even in a fictional-property consultation.
Mock fixtures contain synthetic contacts only.

The write allowlist contains only inquiry events. Send no campaign objects,
action-plan requests, tags/stage/assignment mutations, messages, bookings or showing
requests. Inquiry events can themselves trigger account rules, per the
[events reference](https://docs.followupboss.com/reference/events-post); the live
activation gate above is mandatory. Do not falsify `occurredAt` to bypass workflows.

## Durable delivery and failure handling

After an authorized consultation closes, atomically save the confirmed snapshot,
permission reference and one Neon export job. Duplicate call-end/recovery/webhook
notifications reuse it. Scope local uniqueness to consultation, confirmed version,
provider and destination, with an immutable payload fingerprint. Identical requests
replay status; conflicting payloads need a new confirmed revision and permission.
Retain deduplication evidence while replay is possible. No FUB request runs in the
voice graph or an ephemeral FastAPI background task.

Adapt the existing bounded backend worker; add no Redis/Celery service. Claim a
job under a row lock, commit `sending` with an attempt token before HTTP I/O, release
database locks during the request and fence result updates with that token. Other
workers must not steal/resend `sending` work. Recheck enablement, destination, final
consultation status, confirmed version and current permission/retention immediately
before dispatch. Withdrawal cancels unsent work; it cannot retract a dispatched call.

States: `pending`, `sending`, `retry_wait`, `sent`, `unknown`, `failed`, `ignored`,
`cancelled`. Store attempt count/timestamps, next attempt, sanitized failure code and
minimal receipt/person ID. Keep personal payloads out of logs and audit text.

| Outcome | Required behavior |
| --- | --- |
| Valid 200/201 | Persist sent and returned person ID; do not mistake the person response for an event ID or an idempotency guarantee. |
| 204 | Mark ignored/archived source, not delivered. Do not parse a missing body or replay automatically after source changes. |
| 429 | Persist bounded backoff no earlier than `Retry-After`, respecting rate-limit headers/context and adding jitter. Malformed/missing timing uses conservative bounded backoff; never block voice on a sleep. |
| Definitive credential/permission/validation rejection | Fail or pause the destination with a sanitized actionable code; no repeated bad-key/data submissions. |
| Transport certifies no HTTP request was sent | Bounded retry with the same job/payload and attempt/age limits. |
| Possible submission timeout, post-submission disconnect, 5xx, unrecognized response, malformed success receipt or crash during sending/receipt commit | Hold unknown; no automatic POST replay. Preserve evidence for reconciliation. Lease expiry is not proof of non-delivery. |

FUB deduplicates people by contact details, but the reviewed POST contract does not
establish event idempotency-key support. Do not invent that header or assume person
deduplication prevents duplicate inquiry events. Exactly-once external delivery
cannot be promised. Unknowns remain held across restarts. An authorized operator
must reconcile the correct account's event history and opaque export reference,
with an audited resolution before any separately approved retry. Some events are
[absent from API search](https://docs.followupboss.com/reference/events-get), so
absence of a search result cannot establish non-delivery.

FUB documents status/receipt semantics in the [events contract](https://docs.followupboss.com/reference/events-post).
Its [rate-limit guide](https://docs.followupboss.com/reference/rate-limiting) states
that 429 requests were not processed and specifies `Retry-After`; use actual headers,
not a hardcoded quota. Although its [error guide](https://docs.followupboss.com/reference/error-responses)
recommends backoff, hold ambiguous writes instead of replaying potentially accepted
events without a provider idempotency guarantee.

## Mock-based specifications — written, unexecuted

Written, unexecuted specifications use `httpx.MockTransport`/injectable clients and
synthetic snapshots in `tests/crm/` and `tests/database/test_crm.py`. They do not
establish acceptance or remote automation behavior. This matrix records expected
behavior, including manual acceptance that still requires owner validation.

| Specification | Required evidence |
| --- | --- |
| Optional configuration | `none` needs no keys/client/queue; unknown providers/incomplete enabled settings fail; sync-off sends nothing. |
| Auth and registration | Exact HTTPS events destination, Basic key/empty password and both system headers; redirects/retries off; secrets redacted. |
| Permission boundaries | Absent/false/revoked/expired consent, wrong destination, unfinished call or changed/unconfirmed snapshot produces zero exports. Owner activation is insufficient. |
| Data and fictional examples | Only approved fields; explicit fictional labels; no property/MLS/live-listing claim, transcript, campaign, tags, message or booking request. |
| Voice independence | A stalled CRM mock cannot delay tokens or call finalization; work survives API/worker restarts durably. |
| Idempotency/concurrency | Duplicate end/authorization notifications create one job; payload conflicts reject; two workers make at most one attempt; sent jobs never re-post. |
| Status/errors | Valid 200/201 succeeds; 204 is ignored; malformed receipts become unknown; credential/validation failures stop. |
| Rate limits | 429 honors valid/missing/malformed `Retry-After` with bounded scheduling and attempt/age limits. Use a controlled clock, not real sleeps. |
| Crash/uncertain outcomes | Possible submission, 5xx, lost response/receipt commit and stale sending state become unknown; restart/lease expiry do not resend; missing remote search is inconclusive. |
| Destination/revocation | Provider-off halts dispatch; account changes cannot reroute old payloads; withdrawal cancels unsent work; permissions cannot be reused for a new snapshot. |
| Activation | Live writes require owner approval, separate data permission and validated no-campaign/no-message behavior for new and existing contacts. Mocks cannot prove remote automation behavior. |

Existing isolated-schema fixtures are shared/adapted, without truncating runtime
tables. Exact owner commands are in `crm-setup.md`; core commands remain in
`phase-1.md`. No checks, database operation, system registration, live API read/write,
account configuration, commit or deployment occurred during implementation.
