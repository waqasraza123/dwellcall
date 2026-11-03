# HubSpot — UNVERIFIED

Local branch: `feat/hubspot-crm`, based on merged Phase 4 `ebf6e10`. No new commits, pushes, checks, installs, services, migrations, account changes or live API calls were executed.

Reuse: existing agent snapshots/eligibility, destinations/links/jobs/audits, transactional reservations, admission locks, bounded worker, retry/reconciliation, operator authorization and frontend controls. Migration `20261104_0007` adds nullable company IDs to existing links. GHL and FUB destination fingerprints and GHL snapshot fingerprints remain compatible.

Owner configuration: select `CRM_PROVIDER=hubspot`; set backend `HUBSPOT_ACCESS_TOKEN`, `HUBSPOT_PORTAL_ID` and `CRM_HASH_SECRET`. `HUBSPOT_TOKEN_TYPE=service_key` is the default; existing private app tokens use `private_app`. No browser credential fields or OAuth redirect flow are added. API access requires `CRM_OWNER_APPROVED=true` and `HUBSPOT_API_ENABLED=true`; live synchronization additionally requires `CRM_SYNC_ENABLED=true` and `CRM_AUTOMATIONS_DISABLED_VERIFIED=true`. Existing `.env` and hosting settings are untouched.

The adapter pins date-versioned APIs to `2026-09`, with an explicit `2026-03` compatibility setting. Basic account-details access uses the `oauth` scope in HubSpot's OpenAPI contract. Object scopes: `crm.objects.contacts.read/write`, `crm.objects.companies.read/write`, plus `crm.objects.deals.read/write` when deals are enabled. Property inspection needs the corresponding `crm.schemas.*.read`; explicit property creation needs `crm.schemas.*.write`. Set `HUBSPOT_DECLARED_SCOPES` to the actual granted scopes. Declarations do not prove permission; validation probes reads, and remote authorization remains authoritative.

In CRM → HubSpot: validate the account and owned property mappings. Missing custom properties can be created only after enabling `HUBSPOT_SCHEMA_CREATION_ENABLED` and confirming the explicit operator action. Existing properties are never modified; mismatched types or missing unique markers block setup. Revalidate after creation. Standard contact/company fields are initialized only on new records; subsequent writes target DwellCall-owned properties. Classification uses its own property rather than marketing subscriptions or lifecycle stages.

Phone searches remove only an explicitly configured country calling code (`HUBSPOT_PHONE_CALLING_CODES`, default `["1"]` for the US/Canada). Add actual calling codes for other permitted regions; no country is guessed. Returned contacts still require matching full verified E.164 evidence. Existing unowned email/phone matches require reviewed contact binding. Same-name company matches require an explicit `HUBSPOT_COMPANY_MAPPINGS` mapping from brokerage name to confirmed numeric company ID. Newly managed companies use an independent unique marker. No email addresses or company domains are invented. Listing counts, locations, links, verification and discovery dates are mapped to dedicated fields; complete history remains in Neon.

Optional deals require `HUBSPOT_DEALS_ENABLED`, an existing `HUBSPOT_PIPELINE_ID`/`HUBSPOT_STAGE_ID`, sufficient scope and qualifying listings. Existing human-entered deal values/stages and associations are preserved. Company and deal references reuse the existing durable agent mapping.

Queue and dispatch are separate deliberate actions. Unknown creates require read-only marker lookup before retries; empty lookups never prove absence. Interrupted writes with incomplete evidence remain blocked for independent operator investigation. Property creation also reserves each operation before HTTP. The existing `python -m dwellcall.crm.jobs` worker honors request ceilings, batch intervals, provider backoff and restarts; it is not started or scheduled by this implementation. No CRM calls occur during page loading.

Owner validation from the repository root in an activated Python 3.13 environment, with Node 24 dependencies available:

```bash
python -m pytest tests/crm tests/listings tests/workspace
python -m pytest tests/database/test_hubspot_jobs.py tests/database/test_agent_crm.py tests/database/test_listing_intelligence.py tests/database/test_crm.py
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m ruff format --check apps/backend/src/dwellcall tests migrations
python -m mypy
npm run test:web
npm run typecheck:web
npm run lint:web
npm run format:check:web
npm run build:web
```

Database specifications require a separate disposable `DWELLCALL_TEST_DATABASE_URL`. After reviewing the actual database target, the owner may apply `python -m alembic upgrade head`. Acceptance: validate reads; explicitly create missing properties; preview eligible live identities; queue/dispatch; inspect company/contact/deal associations; confirm replay and human-field preservation; suppress before dispatch; inspect failures; reconcile uncertain writes. Mocked specifications demonstrate fictional listing data; actual synthetic identities remain ineligible for live exports.

Official contracts: [Service Keys](https://developers.hubspot.com/blog/hubspot-service-keys-the-right-api-credential-for-data-integrations), [contacts](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/contacts/create-contact), [properties](https://developers.hubspot.com/docs/api-reference/latest/crm/properties/create-property), [associations](https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide), [official OpenAPI repository](https://github.com/HubSpot/HubSpot-public-api-spec-collection).
