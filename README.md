# DwellCall — AI Real Estate Lead Intelligence

Find new listings. Identify the agents. Build your pipeline.

**New Phase 1 source implementation — UNVERIFIED.** The current deliverable is
bounded synthetic CSV/JSON ingestion, normalized listings and agents, conservative
deduplication, relationships, provenance and permission-controlled operator APIs,
built on the existing FastAPI/Neon foundation. No live data service is claimed.

GoHighLevel is the primary listing-agent CRM provider. Phase 2 source is
implemented and UNVERIFIED, with all calls disabled by default; see the
[GHL owner guide](docs/gohighlevel.md). No direct Zillow, Realtor.com, Redfin, Homes.com, MLS or RESO connector
is implemented or verified. Polling is inactive. DwellCall has no Next.js app yet;
Phase 4 will adapt HVACLine's existing frontend. HVACLine remains untouched.

The [listing ingestion guide](docs/listing-ingestion.md) provides exact owner
checks, migration/import commands and API setup. [Synthetic JSON](data/listings/synthetic-listings.json)
and [CSV](data/listings/synthetic-listings.csv) require only your independent Neon
database, with no listing-provider, LLM, Retell or CRM credentials. They use
fictional Austin listings/agents and reserved example references. This is a
demonstration without external provider requests, not a database-free demo.

## Backend setup — owner execution only

Use Python 3.13 and a new DwellCall Neon project. From this directory:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp -n .env.example .env
```

The owner has supplied database URLs in the ignored `.env`; preserve that file.
The no-clobber copy above is only for fresh checkouts. Use independent pooled/direct
Neon URLs. Leave
`RETELL_TEST_AUDIO_ENABLED=false` and `CRM_PROVIDER=none` for listing ingestion.
Configure a strong `ADMIN_TOKEN` for operator API access.
Dependencies are declared but have not been
installed or resolved together. Installing them does not verify compatibility.

Owner checks and separately controlled migration/startup are in the ingestion
guide. Codex must not execute them without specific owner authorization. All
changes remain UNVERIFIED; the new migration is unapplied. No new dependency or
infrastructure service was added for ingestion.

## Optional voice consultant — preserved, disabled by default

Change `BUSINESS_NAME`, `SUPPORTED_LOCATION`, `CURRENCY`, `PERSONALITY`,
`LLM_MODEL` and `PROPERTY_CATALOG_PATH` in `.env`. The catalog's location and
currency must match. Run from the repository root, or use an absolute catalog path.
[data/properties.json](data/properties.json) is replaceable and contains only
fictional rental, purchase and luxury examples. `PropertyCatalog` in
[catalog.py](apps/backend/src/dwellcall/consultant/catalog.py) is its runtime schema.
The existing graph now includes per-call revisions, spoken readback confirmation,
comparison/objection context and natural closing. State stays in memory; confirming
requirements never grants CRM/storage permission. See [Phase 2 and owner checks](docs/phase-2.md).

## Optional voice boundaries

Only a dedicated, version-pinned Retell **web call** can enter the consultant.
The backend exposes no call-creation, SMS, transfer or public callback endpoint.
Private audio routes are absent by default. Neon serializes admission to one
active or unresolved conversation, with daily count and cost reservations.
The agent duration must be at most 180 seconds and is checked against Retell
before admission. Conversation text and extracted requirements stay in memory;
Neon stores minimal call identity, admission cost and lifecycle evidence.

The first private audio milestone, dependency compatibility and all automated
checks remain **UNVERIFIED**. See [reuse inventory](docs/reuse-inventory.md),
[project state](docs/project-state.md) and [owner runbook](docs/phase-1.md).
Public release, license approval and Render/Vercel setup are later phases.

## Optional consultation CRM — UNVERIFIED

[The implementation plan](docs/implementation-plan.md) preserves the optional
[Follow Up Boss integration](docs/follow-up-boss.md). The owner previously requested
implementation: provider contracts, adapter, durable backend workflow and mocked
specifications are written but unexecuted. It defaults to `CRM_PROVIDER=none` and
requires separate confirmation/data permission. Real dispatch remains disabled
pending core acceptance, owner approval and automation validation. No CRM network
work runs in the voice graph or ingestion pipeline. It does not sync listing
agents. `CRM_PROVIDER` accepts `none|gohighlevel|followupboss`, default `none`.
GHL listing-agent synchronization has separate owner/API/dispatch gates. See [consultation setup](docs/crm-setup.md).

Actual code reuse is recorded in [the inventory](docs/reuse-inventory.md).
80% is a target for applicable code, not a measured or achieved percentage.
