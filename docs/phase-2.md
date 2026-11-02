# Phase 2 consultant — UNVERIFIED

Source extends the existing Phase 1 graph, catalog and Retell stream. It keeps one
configurable property consultant and no RAG, MLS, CRM network calls or multi-agent
architecture. Core Test Audio acceptance and all new specifications remain pending.

## Scenarios and replaceable catalog

`data/properties.json` retains the three original fictional rentals and adds two
purchase examples and two luxury purchase examples. Luxury examples also support
Buying, but Luxury matching uses only explicitly labeled luxury examples; there
is no hardcoded price threshold. All examples remain fictional, without real
addresses, listing identifiers or availability claims.

Each property can declare `scenarios: ["renting", "buying", "luxury"]` as appropriate.
Renting requires `monthly_rent`; Buying/Luxury require `purchase_price`. The earlier
rental JSON shape still works: omitted scenarios default to Renting. Catalog
location/currency must match `SUPPORTED_LOCATION`/`CURRENCY`. Change those values,
`BUSINESS_NAME`, `PERSONALITY`, `LLM_MODEL` and `PROPERTY_CATALOG_PATH` through
configuration; no source edit is needed to replace the business/catalog/location.
The greeting derives offered scenarios from the catalog.

The existing deterministic matcher now checks scenario, budget, minimum bedrooms,
supported city, neighborhood and required feature labels. Rental pet requirements
are enforced against the catalog's explicit pet policy. Purchase pet policies are
not inferred. Unknown locations/features and over-budget examples never become
matches through silent constraint relaxation. The model extracts the full current
snapshot from bounded provider transcript/context; it must clear explicitly
withdrawn preferences and clarify scenario/budget changes.

Comparison resolves only known catalog IDs for the current scenario, with at most
three records and explicit mismatch flags. Monthly rent and purchase price remain
distinct. Replies receive only matching/selected comparison facts, recognize budget,
location, feature and timing objections, and ask which constraint the caller wants
to change. No model response is evidence that a real listing or appointment exists.

## State and confirmation

Each authenticated WebSocket owns one `ConsultationSession`. The shared graph/model
client does not share requirement state between calls. Changes advance the local
revision and invalidate prior readback/confirmation. A completed turn commits its
candidate state; interruption/cancellation closes the stream and does not commit an
unfinished turn. Subsequent extraction still sees the provider's current transcript,
so facts from an interrupted user turn can be collected again.

An explicit recap request produces a deterministic full readback carrying the
revision, scenario, location, currency/budget period, bedrooms and known preferences.
HVACLine's generic spoken-confirmation implementation was extracted/adapted to
Retell role/content fields, requirement-specific wording and Unicode tokens.
Only a clear separate caller yes/confirm after the complete current readback can
confirm it. Partial/interrupted or stale readbacks, qualified yes and corrections
must not grant confirmation. English confirmation phrases are currently supported.
Large summaries ask the caller to reduce details rather than silently omit them.

`confirmed_fields()` prepares a deterministic, bounded summary and requirement
fields compatible with the CRM snapshot. It omits contacts, storage permission and
CRM permission. The operator must separately confirm contact details, obtain data
permissions and use the existing CRM authorization workflow; this method never
enqueues or sends anything. The revision is available on the session and spoken
readback. There is no automatic bridge equating live confirmation with CRM consent.

State and summaries remain in memory for this WebSocket only. They are not newly
stored in Neon, archived in a global session cache, or exposed through an operator
retrieval endpoint. An operator needing post-call review uses the approved provider
review process, confirms the actual snapshot and supplies separate permission to
the existing CRM API. This phase does not add unapproved transcript retention.

Recognized explicit goodbye/stop phrases take a deterministic closing path without
a new LLM request. The final Retell response uses `end_call=true`; Retell's actual
audio/ending behavior still needs live owner acceptance. A closing request does not
imply confirmation, scheduling or contact consent. Human requests receive an
unavailable decision: transfers remain disabled. Socket closure continues to retain
the admission slot until signed/provider-confirmed final evidence.

## Exact owner checks — not executed by Codex

With the existing Python 3.13 virtual environment active, from repository root:

```sh
python -m pytest tests/test_catalog.py tests/test_consultant_state.py tests/test_graph.py tests/test_routes.py
python -m pytest tests --ignore=tests/database
python -m ruff check apps/backend/src tests migrations
python -m ruff format --check apps/backend/src tests migrations
python -m mypy
```

The specifications use synthetic/mock model responses. They cover scenario prices,
hard constraints, comparison mismatches, configurable location/currency, call-state
isolation, interrupted generation, complete/stale/Unicode readback confirmation,
summary compatibility and Retell closing flags. No new dependency or migration is
required for Phase 2; CRM migration `0002` remains separately controlled/unapplied.
These checks are owner commands, not reported passes.

After separately approved private Test Audio setup, manually exercise:

1. Renting, one bedroom, under USD 2,300, with a dog: Willow Terrace Flat.
2. Buying, three bedrooms, under USD 600,000: Maple Courtyard Residence.
3. Luxury purchase, three bedrooms, under USD 2,000,000, private pool:
   Juniper Ridge Estate. Comparing Terrace Sky Residence must flag its USD 2,450,000
   price above budget, not call it a match.
4. Correct/remove a preference, request a recap and confirm only the current full
   readback. Interrupt a recap; a later yes must not confirm the unfinished version.
5. Raise a price/location objection, ask for a human and end the conversation.
   Confirm factual tradeoffs, unavailable transfer, natural closing and signed
   finalization. No booking, text, callback or CRM export should occur.
6. Replace the business identity, catalog location/currency and supported scenarios
   through configuration; confirm the greeting/content follow those values.

Revisit spending reservations for the chosen model: extraction now includes bounded
catalog names/feature context alongside the existing bounded transcript. The
180-second, daily/admission and response-count protections remain in place.
No Test Audio, paid call, service, account change or real CRM sync was performed.
