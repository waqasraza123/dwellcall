# Private audio milestone — UNVERIFIED

All commands below are for **owner execution**. None were executed by Codex.
Installation, checks, schema application, hosting/provider setup and private audio
acceptance remain pending. Do not initiate telephone calls or SMS for this phase.

## Source design

`dwellcall.api` uses the adapted HVACLine FastAPI factory and Neon connection
settings. The only always-present routes are `/health` and `/ready`. Retell routes
are mounted only when `RETELL_TEST_AUDIO_ENABLED=true`:

- WebSocket: `/api/v1/retell/llm/{secret}/{call_id}`.
- Signed event receiver: `POST /api/v1/retell/webhook`.
- Authenticated status reconciliation: `POST /api/v1/retell/admin/calls/{call_id}/refresh`.

Retell appends the call ID to the configured Custom LLM URL. The URL secret is
checked before provider access. The backend retrieves the call using the dedicated
API key, verifies agent/version/web-call identity and active state, and reads that
exact agent version to reject a missing or excessive maximum duration. It then
reserves a single Neon slot under a database guard-row lock. A duplicate call ID
cannot start another model conversation. Reconnection is deliberately disabled in
Phase 1; an interrupted transport requires final status reconciliation and a new
owner-started audio session.

The server sends a typed configuration and AI/fictional-data greeting, handles
heartbeats and streams only the graph's reply text. Newer response requests cancel
older graph streams; transcript updates containing changed user speech cancel
in-flight generation. Retell handles speech interruption. The graph reconstructs
requirements from the provider's bounded current transcript rather than persisting
unspoken model output. It collects a small rental requirement snapshot, applies
deterministic budget/bedroom/pet/neighborhood filters, then drafts a short reply.
It has no tools capable of booking, texting, dialing or transferring.

WebSocket disconnects leave the row `unknown`. Neither timeout nor day rollover
releases unresolved admission. A signed terminal event or authenticated Retell
status lookup can finalize it. Finalization is idempotent and cannot be reversed
by late lifecycle events. An end event arriving before socket admission creates a
tombstone, preventing late replay. The signature is checked against the exact raw
body with Retell's SDK, including its timestamp freshness check. The webhook key
must be the dedicated account key carrying Retell's webhook badge.

## Owner checks without provider calls

After the README installation steps, from the repository root:

```sh
source .venv/bin/activate
python -m pytest tests --ignore=tests/database
python -m ruff check apps/backend/src tests migrations
python -m ruff format --check apps/backend/src tests migrations
python -m mypy
```

These specifications use synthetic credentials and mocked model/provider responses;
they do not initiate calls. They cover the reused settings/health foundation,
private-audio configuration, matching, call identity, signature/body/replay checks,
graph streaming and interruption/authentication boundaries. Check results must be
reported before changing the UNVERIFIED status. Format/lint/type compatibility has
not been established; do not assume these commands pass.

Optional PostgreSQL concurrency specifications require a separately provisioned
test database and the independent runtime URL in ignored `.env`. Export its URL
privately as `DWELLCALL_TEST_DATABASE_URL`, then run:

```sh
python -m pytest tests/database/test_audio_admission.py
```

The fixture enforces the existing runtime/direct/test target isolation rules. It
creates a random `dwellcall_test_*` schema, applies model metadata there, and drops
only that schema afterward. It never truncates existing application tables or
downgrades an existing migration history. Schema creation permission is required.
These tests do not establish that the Alembic revision was applied correctly.

## Independent Neon schema — owner-controlled write

Provision a fresh DwellCall Neon project. Use its pooled URL for `DATABASE_URL`
and direct URL for `DIRECT_DATABASE_URL`; retain TLS. Never target HVACLine's
project. Review the new root revision `20261103_0001`; it contains only a singleton
admission guard and minimal audio session evidence. No migration runs at startup.

When the owner approves applying this schema to that independent database:

```sh
python -m alembic upgrade head
python -m alembic current
```

No migrations have been run. Downgrade refuses to erase stored admission evidence.
The subsequent optional CRM implementation adds unapplied revision `20261103_0002`.
Review it in `crm-setup.md` before running `upgrade head`, which now includes both
revisions. CRM defaults off and does not require those extra tables for core voice.

## Private Retell setup — owner-controlled configuration

Use a separate DwellCall Retell workspace/key and dedicated Custom LLM agent.
Do not reuse HVACLine credentials or connect a telephone number. In the ignored
`.env`, configure `RETELL_API_KEY`, `RETELL_AGENT_ID`, the exact numeric
`RETELL_AGENT_VERSION`, and an independent `LLM_API_KEY`. The default model name
is configurable; verify the chosen model supports structured JSON output and
streaming before acceptance. Use two different random URL-safe secrets of at
least 32 characters for `RETELL_WEBSOCKET_SECRET` and `ADMIN_TOKEN`.

The owner must configure a private TLS-capable persistent backend address and
these Retell agent values before starting audio:

- Response engine: Custom LLM. URL:
  `wss://YOUR-DWELLCALL-HOST/api/v1/retell/llm/YOUR-PRIVATE-URL-SECRET`.
  Retell adds `/{call_id}`; do not add it yourself.
- Maximum call duration: `180000` milliseconds or lower, matching the backend
  duration limit (Retell's supported minimum is 60 seconds).
- Webhook: `https://YOUR-DWELLCALL-HOST/api/v1/retell/webhook`; enable
  `call_started`, `call_ended` and `call_analyzed`.
- Keep the agent private, with no telephone number, public widget, SMS or transfer
  integration. Choose minimal provider retention, such as
  `data_storage_setting=basic_attributes_only`, and confirm microphone consent in
  the dashboard. DwellCall does not persist transcript/audio content.

Set a conservative `CONVERSATION_RESERVED_COST_CENTS` for a full 180-second session
and bounded model work, and a `CONVERSATION_DAILY_BUDGET_CENTS` covering permitted
sessions. Both intentionally default to zero, which blocks activation. Daily count
defaults to five and cannot exceed ten. Each accepted response can invoke one
extraction and one streaming generation, capped at 500 output tokens each and
20 responses total. Input transcript bounds are 60 utterances, 2,000 characters
per utterance and 30,000 characters total. Reservations are not refunded on end.

Cost reservations are an **admission estimate**, not a provider billing cap.
Retell starts dashboard audio before our adapter admits model work; rejected
connections can still incur provider costs. Configure provider account spending
controls independently. No backend change can prevent spending initiated directly
through the owner's dashboard. Revisit the cost estimate when changing voice,
model, duration or provider pricing.

Once those owner-controlled settings, checks and schema are ready, set
`RETELL_TEST_AUDIO_ENABLED=true` in the ignored `.env`. Start the backend in the
foreground, from the repository root:

```sh
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000 --ws-max-size 65536 --no-access-log --log-level warning
```

Retell needs a separately approved TLS route to this process; local loopback alone
is not reachable by Retell. Do not deploy to Vercel functions for the WebSocket.
The URL contains a credential: configure ingress/platform logging to redact it.
Uvicorn's warning log level avoids its informational WebSocket-path logging.
Leave external conversation tracing disabled unless deliberately approved.

This runbook does not authorize Codex to change a provider, start a service,
deploy, provision a database or initiate any paid session.

## First acceptance conversation

The owner opens the dedicated agent's **Test Audio** tab, grants microphone access
and starts one private web conversation. The expected flow is AI/fictional-data
disclosure, then budget/bedroom collection. For “one bedroom under 2,300 a month,
with my dog,” the only matching example is Willow Terrace Flat at USD 2,150.
For “two bedrooms under 2,000,” the agent must explain that none match and ask
which constraint the caller wants to change. Interrupt a response and confirm the
new utterance replaces generation. Do not treat this as verified until heard.

Confirm that a wrong URL secret, unknown call, phone call, wrong agent/version
and agent duration over 180 seconds fail before model work. Confirm another
session is blocked while the first is active or unresolved. Observe the signed
end event, then confirm a new authorized web call can be admitted within quotas.
Confirm duplicate/reordered terminal events do not reopen a session. Confirm
there are no stored raw transcript/audio/requirements in DwellCall's database.
Listen through the duration limit once under separate owner-paid-test approval;
the agent must end within the configured provider maximum.

If the socket closes without a signed final event, retain the slot. To reconcile,
the owner privately exports `DWELLCALL_API_ORIGIN`, `DWELLCALL_CALL_ID` and
`DWELLCALL_ADMIN_TOKEN`, then runs:

```sh
curl --fail-with-body --request POST --header "X-Admin-Token: ${DWELLCALL_ADMIN_TOKEN}" "${DWELLCALL_API_ORIGIN}/api/v1/retell/admin/calls/${DWELLCALL_CALL_ID}/refresh"
```

Only Retell's final `ended`, `error` or `not_connected` state releases the slot;
lookup failure or an ongoing state keeps it blocked. This endpoint never dials
or force-ends a call. Process restart does not clear the database reservation.
Report dependency/check results and these manual outcomes before moving to Phase 2.

## Protocol and library references

The implementation uses Retell's official Python example as a protocol reference,
with authentication and bounded tasks added around its wire format:
[official Python example](https://github.com/RetellAI/retell-custom-llm-python-demo),
[WebSocket protocol](https://docs.retellai.com/api-references/llm-websocket),
[server setup and WebSocket authentication](https://docs.retellai.com/integrate-llm/setup-websocket-server),
[raw-body signature verification](https://docs.retellai.com/features/secure-webhook),
[call lookup](https://docs.retellai.com/api-references/get-call),
[agent version/duration configuration](https://docs.retellai.com/api-references/get-agent),
[LangGraph streaming](https://docs.langchain.com/oss/python/langgraph/streaming),
[ChatOpenAI integration](https://docs.langchain.com/oss/python/integrations/chat/openai).

No third-party example implementation was vendored. HVACLine's source licensing
and dependency/third-party notices must be reviewed before the Phase 5 MIT release.
