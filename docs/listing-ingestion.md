# Listing intelligence Phase 1 — UNVERIFIED

Commands below are for owner execution from the repository root. Codex has not
run them. No checks, database connection, migration, service or provider acceptance
is claimed. No new dependency/infrastructure service is introduced.

## Files and contracts

`listings/schemas.py` contains runtime contracts; `contracts.py` defines provider
interfaces. `database/models/intelligence.py` defines normalized records. The unapplied migrations are `20261103_0003_listing_intelligence.py` and
`20261103_0004_listing_review_resolution.py`.

JSON requires exactly `{"synthetic":true,"listings":[...]}`. CSV requires
`synthetic` and `source_listing_id` headers and `true` per row. UTF-8/BOM, quoted
CSV and JSON agent arrays in CSV cells are supported. Unknown fields, duplicate
keys/headers and invalid types fail validation. Malformed envelopes reject the
file; bad rows return only indexes/generic codes while valid rows commit with a
partial result. Unexpected database failures roll back the entire import.

Listings accept stable source ID; optional authority namespace/reference; address,
city/state/ZIP/country; decimal price/currency; original date/UTC update; beds,
baths/area; property/listing type; URL/status; bounded metadata and co-agents.
Only source ID is intrinsically required, but enough supplied or previously stored
geography must satisfy source permissions. Unknown fields stay unknown; no
geocoding or invented facts. Upstream status mapping must be explicit.

Agents support source/authority IDs, name, brokerage, profile URL and explicitly
published business contacts. Contacts include kind, directness, source reference,
optional URL/confidence and source verification claim/time. Phones require E.164;
emails are validated, never generated. Office/direct/mobile stay separate. CSV
contacts start unverified. Trusted demo evidence becomes `synthetic_verified`,
never real `verified`. No independent contact verification occurs.

Omitted JSON facts preserve previous source values; explicit null clears optional
facts. Omitted agents/contacts preserve them; empty arrays deactivate them. Blank
CSV cells are omitted; use JSON for nulls. Changed property facts require a newer
source timestamp. Older updates are stale; unordered/conflicting updates are held.
Pending/sold/removed updates preserve known facts. Existing source IDs receive
updates even after leaving admission price/status filters.

## Identity and permission behavior

Deduplication uses `(source key, source listing ID)`. Cross-source listing merges
require approved authority namespace/reference and compatible address evidence.
Address alone does not merge relistings. Agent merges use source/authority IDs or
fresh source-trusted verified direct contact evidence accompanying a strong ID. Shared names, brokerages
and office phones never suffice. Conflicts are held; weak agents stay listing-local
with review flags and no activated contact evidence. Weak contacts cannot merge
people or enrich an existing person. Local aliases cannot acquire new strong IDs
automatically. Co-agent/multiple-listing relationships are preserved. Admin review
resolution is described below; synthetic/weak/unresolved identities remain ineligible for CRM export.

Source observations/revisions preserve property facts. Current permitted facts are
selected per field by source update time, collection time and source key, with
source/version/attribution evidence. A partial patch advances collection evidence
for its merged snapshot; it does not independently reverify omitted facts. Agent
facts/contact evidence have separate provenance. Contact values are excluded from
listing snapshots, revisions, run results and audit events.

The migration registers only `synthetic-files`: fictional US/TX/Austin data,
example.com references, demo authority IDs, 30-day retention and export forbidden.
This grants no real-data rights. Other sources need explicit operator permission
configuration and an opaque evidence reference; licenses remain outside the app.
Provider/mode are immutable. Geography/reference-host/authority scope changes
require purging source observations first. Display/storage/contact rights can be
revoked immediately. Reference URLs are never fetched. Future HTTP connectors
still need DNS/redirect/SSRF controls.

`ADMIN_TOKEN` permits full contacts and mutations. Optional distinct
`LISTING_VIEWER_TOKEN` permits reads with contact values/references restricted.
Tokens must stay on trusted servers/operator tools. Suppression deactivates contact
evidence and is irreversible through ingestion or review approval. Retained strong
IDs, listing-local alias hashes and suppression-only direct-contact hashes block
reintroduction after updates, changed IDs, permission changes and purge/reimport.
Office phones never identify or merge people. Suppression aliases only withhold
records; they never authorize merging. A person returning with entirely unrelated
evidence cannot be recognized: unidentified records remain held with no contact
activation/export until an operator provides explicit resolution evidence. This
is no claim of identity recognition without evidence. Minimal suppression IDs,
decisions, audits and run hashes/counts remain without raw contact payloads.

Retention hides expired data on reads. Owner maintenance physically removes at
most 50 source observations plus bounded old history/contacts/review-payloads/orphans per
invocation. Repeat as needed. No automatic TTL is claimed. Listing/agent reads
also respect current display/storage/contact rights.

## Owner validation

After README environment setup, run:

```sh
source .venv/bin/activate
python -m pytest tests/listings
python -m pytest --ignore=tests/database
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m ruff format --check apps/backend/src/dwellcall tests migrations
python -m mypy
```

Set `DWELLCALL_TEST_DATABASE_URL` securely in your shell to a separately provisioned
disposable database, distinct from runtime Neon. The existing fixture checks target
isolation, creates a random schema and drops only that schema; it does not migrate.

```sh
python -m pytest tests/database/test_listing_intelligence.py
```

Written, unexecuted specifications additionally cover conflicting IDs, shared office
phones, duplicate agents, weak approval scope, suppression after purge/new IDs,
immutable concurrent decisions, transactional audit rollback and repeat imports.
Existing specifications cover files/limits, missing fields, synthetic
labels, auth/roles, replay conflicts, updates/stale records, shared agents/co-agents,
conservative matching, revocation/masking, suppression/expiry/deletion, concurrent
import exclusion and transactional crash rollback. Results remain pending.

## Owner-controlled database writes

Review the new migration and independent direct Neon URL first. `upgrade head`
also applies earlier unapplied revisions. These commands write your database:

```sh
python -m alembic upgrade head
python -m dwellcall.listings.importer --file data/listings/synthetic-listings.json --request-id 11111111-1111-4111-8111-111111111111
python -m dwellcall.listings.importer --file data/listings/synthetic-listings.json --request-id 11111111-1111-4111-8111-111111111111
python -m dwellcall.listings.importer --file data/listings/synthetic-listings.csv --request-id 22222222-2222-4222-8222-222222222222
```

The second invocation should replay the first run. JSON should initially produce
three listings/three agents, including shared/co-agents; CSV adds two listings/one
agent. All contacts remain unverified. New content/filters require a NEW UUID;
transport/commit uncertainty requires the SAME UUID/bytes/filters to recover safely.
Default admission: 250 rows/2 MiB per file, 24 new runs/5,000 received rows per UTC
day. Replays consume no extra run; rejected rows count toward row limits.

```sh
python -m dwellcall.listings.importer --file data/listings/synthetic-listings.json --filters data/listings/filters.example.json --request-id 33333333-3333-4333-8333-333333333333
python -m dwellcall.listings.importer --source synthetic-files --purge-expired
```

Import/maintenance share transaction advisory locking and bounded SQL/job budgets.
Busy work returns a retryable error. Committed runs and file/filter/permission
digests survive restarts. Duplicate observations do not refresh retention. There
is no daemon, HTTP fetch, live-feed cursor or polling schedule.

## Owner-controlled API demonstration

With the schema and strong admin token configured, the owner may start:

```sh
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

In another owner terminal with `ADMIN_TOKEN` securely set in the shell:

```sh
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/intelligence/providers
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Idempotency-Key: 44444444-4444-4444-8444-444444444444' -H 'Content-Type: application/json' --data-binary @data/listings/synthetic-listings.json 'http://127.0.0.1:8000/api/v1/intelligence/sources/synthetic-files/imports?format=json'
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/intelligence/listings
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/intelligence/agents
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/intelligence/runs
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" http://127.0.0.1:8000/api/v1/intelligence/reviews
```

Listing/agent pagination accepts `page`, `page_size` (max 100), `mode=synthetic|live`.
Admin routes: `GET /sources`, `PUT /sources/{key}` (full `SourcePermissionInput`
JSON), `POST /agents/{id}/suppress`, `POST /sources/{key}/purge`. Purge defaults
to expired-only; `?expired_only=false` explicitly deletes source observations in
bounded batches, retaining other sources and minimal audit/suppression evidence.
Inspect provenance, missing fields, associations and viewer masking manually.

## Minimal authenticated review workflow — UNVERIFIED

No UI, new framework or provider calls are introduced. All three review routes
require `ADMIN_TOKEN`; viewer credentials are denied. `GET /reviews` lists bounded
recent review evidence/status; `GET /reviews/{id}` adds permission/retention-aware
candidate summaries without raw contact payloads. POST resolution uses the same
Neon transaction/advisory lock as imports, suppression and purge, plus a review
row lock. Busy attempts return `INGESTION_BUSY`; retry the identical decision.

Using real UUIDs returned by the API, set `REVIEW_ID` and `CANDIDATE_ID` privately:

```sh
curl --fail-with-body -H "X-Admin-Token: $ADMIN_TOKEN" "http://127.0.0.1:8000/api/v1/intelligence/reviews/$REVIEW_ID"
curl --fail-with-body -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' --data "{\"decision\":\"approve\",\"candidate_id\":\"$CANDIDATE_ID\",\"evidence_reference\":\"operator-case-001\"}" "http://127.0.0.1:8000/api/v1/intelligence/reviews/$REVIEW_ID/resolve"
```

To reject a different pending review:

```sh
curl --fail-with-body -X POST -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' --data '{"decision":"reject","evidence_reference":"operator-case-002"}' "http://127.0.0.1:8000/api/v1/intelligence/reviews/$REVIEW_ID/resolve"
```

The opaque evidence reference points to the operator's separately retained review
evidence; do not put personal data or documents in it. Audit evidence records the
review fingerprint, decision, candidate, timestamp and authenticated-admin role.
The existing shared token does not distinguish individual operators.

Decisions are immutable. Repeating the same body returns the stored result and
creates no second audit; a competing different body returns 409. Approval accepts
only a proposed candidate in the same data mode. Suppressed candidates cannot be
approved, and later suppression still overrides earlier approvals. Malformed,
unapproved-namespace and out-of-order inputs require upstream correction; reviews
without proposed identity candidates can be rejected but cannot be approved.

Approval is staged: reimport the reviewed file with a **new request UUID** to apply
it atomically. Reusing the original UUID returns the historical import result and
never mutates records. Check `applied_at` / `requires_reimport`. Approval binds the
reviewed source observation to the selected entity; it does not reassign global
authority IDs or merge every record attached to either entity. Rejections withhold
the proposed association and remain effective on repeated imports. Changed agent
facts/contacts or permission version need fresh review; listing approval applies
only to the exact record evidence. Other unresolved holds remain blocking.

Review decisions survive purge; bounded cleanup redacts expired/source-purged
review payloads to identity/evidence hashes and minimal decision metadata. Reads
still hide expired/revoked review evidence. There is no unsuppress, global identity
repair, bulk review dashboard in Phase 1; gated CRM dispatch is described in the Phase 2 GHL guide.

Owner manual checks: inspect both sides of a conflict; approve and reimport with a
new UUID; confirm only that association changes, global IDs stay fixed and one
resolution/application audit is written. Reject a separate proposal, then repeat
its import. Race opposing decisions and confirm one winner (retry 429); repeat
that winner and confirm no extra audit. Suppress before/after approval, change the
source agent ID/brokerage, purge and reimport: confirm suppression persists and
contacts stay inactive. Check viewer denial, revoked/expired evidence hiding, and
`crm_export_eligible=false` for synthetic/weak/unresolved agents. Run the exact pytest, Ruff,
mypy and isolated-database commands above; results remain pending.

## Deferred and inactive

The file provider is implemented; the licensed-feed interface awaits an actual
authorized connector. A separate permission-approved live file source may use synthetic=false for Phase 2;
synthetic sources still require synthetic=true and never export. Portal status is
`not_integrated`; credentials alone cannot activate it. Poll frequency is metadata.
Phase 2 GHL mapping/dispatch/reconciliation and guarded provisioning are now
implemented but UNVERIFIED; see [GHL owner commands](gohighlevel.md). `CRM_PROVIDER`
accepts `none|gohighlevel|followupboss`, default none. Existing FUB consultation exports
are never called by ingestion. AI enrichment, scheduling and the adapted website
are later phases. Keep private audio off. No paid resources, outreach or provider
acceptance are inferred from these implementation files.
