# GoHighLevel Phase 2 — UNVERIFIED

No checks, migrations, services or CRM calls were executed. Existing environment
files are unchanged. GHL is the primary listing-agent provider; default provider
`none` and all API/dispatch/provisioning gates remain off. FUB consultation exports
retain their existing settings, routes and behavior.

Owner configuration (set securely; never paste credentials into notes):

- `CRM_PROVIDER=gohighlevel`, `CRM_HASH_SECRET` (stable secret, at least 32 chars),
  `GHL_PRIVATE_INTEGRATION_TOKEN`, `GHL_LOCATION_ID`, `CRM_OWNER_APPROVED=true`.
- `GHL_API_ENABLED=true` permits explicit API inspection. `CRM_SYNC_ENABLED=true`
  also requires `CRM_AUTOMATIONS_DISABLED_VERIFIED=true`; this gate requires owner
  review of location automations before contact/tag/opportunity writes.
- `GHL_AUTO_QUEUE=true` reserves eligible agents during imports; defaults false.
- Private token scopes: `contacts.readonly`, `contacts.write`, `locations.readonly`,
  `locations/customFields.readonly`; optional `opportunities.readonly` and
  `opportunities.write`. Opaque PIT scopes cannot be decoded: setup reports observed
  read capabilities and separately labels declared/unprobed write permissions.
- Create/select five dedicated **contact** fields in the existing location:
  `DwellCall Agent ID` (TEXT), `DwellCall Revision` (TEXT), `DwellCall Properties`
  (LARGE_TEXT), `DwellCall Brokerage` (TEXT), `DwellCall Sources` (LARGE_TEXT).
  Setup discovers these names. Alternatively set `GHL_CUSTOM_FIELDS` to a JSON
  object mapping `agent_id`, `revision`, `properties`, `brokerage`, `sources` to
  those dedicated field IDs; setup validates model/types. Setup creates no fields.
- Optional JSON-array `GHL_TAGS`, `GHL_LEAD_SOURCE`. Existing notes, nonempty name/
  email/phone/source and unrelated fields are preserved; tags use the additive API.
- Opportunities: `GHL_OPPORTUNITIES_ENABLED=true`, existing `GHL_PIPELINE_ID`,
  `GHL_PIPELINE_STAGE_ID`, `GHL_QUALIFIED_MIN_LISTINGS` (default 1), and JSON-array
  `GHL_QUALIFYING_STATUSES` (default `["active"]`). No invented opportunity value.

Authenticated routes under `/api/v1/crm/ghl` use `X-Admin-Token`:

- `GET /status`; `POST /setup` with `{"evidence_reference":"owner-setup-001"}`.
- `GET /agents?page=1&page_size=25` previews eligibility, current property/source
  references, contact mapping and sync status. Synthetic data is always excluded.
- `POST /agents/queue` with `{"agent_ids":["AGENT_UUID"]}`; `POST /jobs/process`
  runs one bounded batch. No background worker starts automatically.
- `GET /jobs?agent_id=AGENT_UUID&status=unknown`; `GET /jobs/JOB_UUID/audit`.
- `POST /jobs/JOB_UUID/retry` or `/reconcile`, each with an opaque
  `evidence_reference`. Retry accepts only confirmed-safe failures; reconciliation
  uses GHL lookup. Absence after an uncertain create never permits another create.
- `POST /agents/AGENT_UUID/bind` with `contact_id` and `evidence_reference` explicitly
  maps an existing contact after matching verified direct evidence. No remote write
  occurs. Existing unowned matches are held until bound; split email/phone matches
  are never silently upserted. Global IDs are never reassigned.

Local file ingestion now accepts `synthetic:false` (CSV `false`) only for a separate
registered `provider=file`, `data_mode=live` source with explicit storage/contact/
export rights and trusted verified direct evidence. Synthetic envelopes remain
required for synthetic sources. No live connector or contact verification service
is introduced. Expiry, source revocation, suppression, weak identity and unresolved
or rejected reviews block dispatch. Property facts come only from export-permitted
source observations. Auto-queue is capped at 50 agents per import; `more_available`
indicates work available through paginated preview/manual queueing.

Jobs reuse Neon transactions, advisory/row locks, attempt fencing, existing job
budgets/client/CLI and bounded batches. Sending reservations commit before HTTP;
interrupted work becomes unknown, never blindly replayed. Destination backoff and
authentication pauses persist. The ingestion lock serializes sends with suppression,
review and permission changes. Sent payloads are cleared; bounded maintenance
expires other payloads while retaining mappings and uncertain-outcome tombstones.
Token rotation preserves destination mapping; do not rotate `CRM_HASH_SECRET`
without migrating existing destination/identity mappings. Uncertain jobs whose
lookup/evidence cannot confirm delivery remain blocked for operator investigation.

Optional `POST /locations/provision` is gated by `GHL_PROVISIONING_ENABLED`, a
separate scoped `GHL_AGENCY_TOKEN`, `GHL_COMPANY_ID`, declared `locations.write`,
owner approval and an explicit request containing `approve_external_creation`,
`agency_scope_confirmed`, `plan_permits_provisioning` (all true), opaque plan/owner
evidence references and required location address/timezone fields. Owner must
confirm plan entitlement; it cannot be inferred from a location PIT. Identical
provisioning requests are durably reserved before HTTP and never blindly retried,
including after uncertain outcomes. Provisioning does not replace environment
configuration or select the new location. No resource was created in this session.

Owner validation, from repository root with a separate disposable
`DWELLCALL_TEST_DATABASE_URL` configured securely:

```sh
source .venv/bin/activate
python -m pytest tests/crm tests/listings
python -m pytest tests/database/test_agent_crm.py tests/database/test_listing_intelligence.py tests/database/test_crm.py
python -m pytest --ignore=tests/database
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m ruff format --check apps/backend/src/dwellcall tests migrations
python -m mypy
```

After reviewing migration 0005 and the independent database target, owner-only:

```sh
python -m alembic upgrade head
```

After separate owner configuration/approval, explicit worker/maintenance commands:

```sh
python -m dwellcall.crm.jobs
python -m dwellcall.crm.jobs --purge-only
```

Manual acceptance: inspect setup/missing fields, import permitted live fixtures,
queue twice, confirm one contact and multiple property references; add a property
and confirm contact ID is stable. Confirm manual CRM fields/tags/notes survive.
Exercise suppression/revocation after reservation, 429/auth pauses, interrupted
worker recovery and uncertain lookup before retry. Keep all live gates off until
owner results establish acceptance. The API v2 opportunity endpoints are documented
as deprecated; owner validation must establish account compatibility.

API contracts: [contacts search](https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/contacts/search-contacts-advanced/),
[contact updates](https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/contacts/update-contact/),
[custom fields](https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/locations/get-custom-fields/),
[opportunity creation](https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/opportunities/create-opportunity/),
[plan-restricted location creation](https://marketplace.gohighlevel.com/docs/2021-07-28/ghl/locations/create-location/).
