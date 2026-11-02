# DwellCall

Your AI Property Consultant. The right place starts with a conversation.

**Phase 1 implementation — UNVERIFIED.** This directory contains an extracted
HVACLine FastAPI foundation and the minimum new Retell Custom LLM + LangGraph
rental consultant. The first acceptance milestone is an owner-run private Retell
Test Audio conversation using three fictional Austin rentals. It has not happened.

The website and outbound workflow remain deferred. Their implementation must
adapt HVACLine's existing Next.js application and outbound service. No Git history,
credentials, environment files, historical notes, provider identifiers or hosting
configuration were imported. The owner has authorized publishing this Phase 1
source to `waqasraza123/dwellcall`; publication does not verify or activate it.

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
`RETELL_TEST_AUDIO_ENABLED=false` until completing the private setup in
[the Phase 1 runbook](docs/phase-1.md). Dependencies are declared but have not been
installed or resolved together. Installing them does not verify compatibility.

Owner checks and the separately controlled migration/startup sequence are in the
runbook. Codex must not execute them without the owner's specific authorization.

## Configuration and data

Change `BUSINESS_NAME`, `SUPPORTED_LOCATION`, `CURRENCY`, `PERSONALITY`,
`LLM_MODEL` and `PROPERTY_CATALOG_PATH` in `.env`. The catalog's location and
currency must match. Run from the repository root, or use an absolute catalog path.
[data/properties.json](data/properties.json) is replaceable and contains only
fictional rentals. `PropertyCatalog` in
[catalog.py](apps/backend/src/dwellcall/consultant/catalog.py) is its runtime schema.
Buying, Luxury, persistent requirement updates and richer objection/comparison
flows are Phase 2 work.

## Boundaries

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
