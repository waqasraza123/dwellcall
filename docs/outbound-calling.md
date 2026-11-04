# Retell + Telnyx outbound — UNVERIFIED

Source only. No checks, installs, migrations, services, provider changes or calls ran.
HVACLine was read-only. Its outbound service/model/preflight/security/recovery and
frontend request-lock/receipt patterns were adapted to DwellCall. ElevenLabs code,
agent configuration and credentials were not imported. Existing CRM integrations
and discovery remain separate. No campaign or automatic dialing path exists.

## Owner setup

1. Follow [Retell's Telnyx setup](https://docs.retellai.com/deploy/telnyx).
   Create an FQDN Elastic SIP trunk pointing to `sip.retellai.com` with SRV DNS;
   use credential authentication, E.164 and compatible codecs. Select an outbound
   voice profile with approved destinations, concurrency, duration and spending
   controls. Attach your authorized Telnyx number. Retell recommends TCP; this
   adapter accepts TCP or TLS. No Telnyx API key is needed by DwellCall.
2. Import that number into Retell with the regional Telnyx termination hostname
   and SIP username/password. Configure `X-Telnyx-Username`. DwellCall sends the
   configured username header on every outbound creation. Retell's SIP connection
   test does not establish that custom headers or real outbound calls work.
3. Create/publish a dedicated DwellCall **Custom LLM** agent, distinct from the
   web agent, and pin its numeric version. Its response engine URL must be
   `wss://YOUR-API/api/v1/retell/llm/YOUR-EXISTING-WS-SECRET`; Retell appends the call ID.
   Set `max_call_duration_ms` to at most 180000, `ring_duration_ms` to at most
   25000, `data_storage_setting=basic_attributes_only`, retention at most seven
   days and `enable_dnc_detection=true`. Disable contact memory read/update and
   pre/post-session tools. These settings prevent provider transcript/recording
   storage; DwellCall stores neither. Retell's live spoken transcript alone feeds
   the existing consultant; generated text is never appended as spoken history.
4. Set the agent webhook to `https://YOUR-API/api/v1/retell/webhook`, subscribing
   to `call_started`, `call_ended`, `call_analyzed`. Verification uses the existing
   Retell API-key signature verifier against original request bytes. Proxy logging
   must redact WebSocket secret paths and must not log bodies/audio/transcripts.
5. Extend owner-managed configuration from `.env.example`; preserve existing
   credentials. Set the dedicated agent/version, imported caller, public API
   origin, SIP username, stable separate hashing secret and approved recipients.
   Record fresh, purpose-specific recipient consent outside discovery before each
   request; the two unchecked operator confirmations record its authorization and
   DNC review. Revocations belong in `OUTBOUND_SUPPRESSED_NUMBERS` or the durable
   suppression API. Provider DNC handling and spoken DNC requests also suppress.
6. Reserve a conservative cost in US cents covering the maximum Retell, carrier
   and LLM usage; set a daily reservation ceiling. Reservations are never refunded
   automatically. Limits are one global active/unresolved audio slot (shared with
   web calls), five attempts per UTC day, one per recipient, 300-second cooldown.
   Failed preflights also consume an admitted attempt/reservation. Carrier-side
   spending/destination controls remain necessary. Confirm carrier permissions,
   rates, caller ID and authorization before enabling live calling. Non-US
   countries, including Pakistan, require explicit entries in both country sets;
   they are disabled by default. Number metadata does not establish ownership.
7. The existing operator login and server bridge need no new browser secret.
   Open `/calls`. With `OUTBOUND_ENABLED=false`, development-only
   `OUTBOUND_MOCK_ENABLED=true` exercises the full durable form/status workflow
   without Retell, Telnyx or LLM requests. Supply a synthetic caller/allowlist,
   agent/version, stable hashing secret and positive simulated budget; progress
   finishes after 15 seconds when read. Simulation is labeled and also consumes
   the shared quotas. It survives restarts and never admits an audio socket.

## Recovery and transfer

Authenticated endpoints use `X-Admin-Token`, under `/api/v1/outbound`:
`GET availability|calls|calls/{id}|requests/{request_id}`;
`POST preflight|calls|controls|suppress`;
`POST calls/{id}/refresh|bind|stop|carrier-ended`.
Initiation takes a UUID `request_id` (also the `Idempotency-Key` when supplied),
canonicalizable international `phone_number`, `scenario=renting|buying|luxury`,
`consent=true`, `consent_version=dwellcall-ai-call-v1`,
`recipient_consent_confirmed=true`, `do_not_call_checked=true`.
`bind` takes an existing `provider_call_id`; `carrier-ended` requires strict
`all_carrier_legs_ended=true`. `controls` takes boolean `calls_paused` and
`transfers_paused`; `suppress` takes `phone_number`. All routes require admin auth.

Creation uses [Retell's phone-call API](https://docs.retellai.com/api-references/create-phone-call)
exactly once per local request. The reservation commits before HTTP; the shared
guard fences the bounded send against recovery/release. Timeout, malformed receipt
or ambiguous failure holds the slot as unknown. Reconciliation retrieves the bound
call or performs a bounded metadata lookup; no match never authorizes redial.
An operator can bind a known receipt only after full call/agent/version/caller/
recipient/authorization verification. Final states cannot be revived by late
start events. Late transfer evidence conservatively retains the carrier slot.
Retell's `registered` receipt means dialing; ringing is not synthesized without
separate provider evidence, and acceptance never means answered.
Disconnection/restart never releases a reservation by timeout. Orphaned reserved
requests become unknown on read. Inspect both accounts, then explicitly confirm
every carrier leg ended; recovery refuses an in-flight send. Missing browser
requests stay locked for investigation; do not clear a missing key until the
original sender has stopped and account/DB history confirms no call can emerge.

Transfer uses the [Custom LLM response `transfer_number`](https://docs.retellai.com/api-references/llm-websocket)
for imported numbers, after the complete confirmation question is present in
Retell's spoken transcript and a separate clear yes. The destination comes only
from `OUTBOUND_HUMAN_NUMBER`; caller-ID passthrough is off. Interruption or an
uncertain send leaves transfer unconfirmed and never retries. REFER acceptance
does not establish human answer. Confirmed transfer cancellation can finalize
failure; otherwise operator-confirmed carrier completion releases the reservation.

Keep transfer disabled. [Telnyx's published external-transfer guide](https://support.telnyx.com/en/articles/13117410-how-external-call-transfers-work)
describes inbound call matching, which does not establish compatibility for this
outbound-originated PSTN transfer. Before enabling, obtain account-specific REFER/
PSTN/caller-ID confirmation and test declined/unavailable/no-answer handling.
Independently enforce the declared `OUTBOUND_TRANSFER_MAX_SECONDS` and spending
cap on transferred carrier legs, and reserve their maximum estimated cost. The
two confirmation flags are owner attestations, not an implemented carrier timer.
The AI duration limit and Retell stop request cannot establish transferred-leg
termination. Emergency pause is durable; Stop call is a separate deliberate action.

Local call rows retain keyed hashes, request IDs, minimal consent/receipt/status/
cost/transfer evidence and timestamps. No raw recipient/caller phone is stored in
these tables. Keep the stable hash secret; rotating it requires an explicit
suppression/quota migration. Evidence and suppression tombstones are retained to
prevent replays; provider retention does not delete local authorization evidence.

## Owner validation

From the repository root, with Python 3.13 and Node 24, owner-only:

```bash
python -m pip install -e '.[dev]'
npm ci
python -m pytest tests/outbound tests/test_retell.py tests/test_routes.py tests/test_graph.py tests/test_consultant_state.py
python -m pytest tests/database/test_outbound_calls.py tests/database/test_audio_admission.py
npm run test:web -- src/features/outbound/api.test.ts src/lib/bridge-policy.test.ts 'src/app/api/ops/[...path]/route.test.ts'
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m mypy
npm run typecheck:web
npm run build:web
```

Database specifications require the existing isolated-fixture configuration and a
separate disposable `DWELLCALL_TEST_DATABASE_URL`; never use a live target.
After independently reviewing the migration target, owner-only:

```bash
python -m alembic upgrade head
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

In a separate owner terminal: `npm run dev:web`.

Manual acceptance: first keep live/transfer off and use simulation; sign in,
submit once, double-click, refresh mid-request, inspect final duration/history,
pause and recover. Check invalid consent, unapproved/suppressed/non-US recipients,
quota/budget rejection, timeout/unknown recovery, webhook ordering, and phone socket
isolation/cancellation with mocks. Then, only after separately authorizing paid
calling, configure the real agent/trunk, pass preflight and initiate one consented
allowlisted call. Check greeting/disclosure, renting/buying/luxury continuity,
recommendations/comparisons/objections, interruption, explicit stop/DNC, 180-second
cutoff, terminal webhook evidence, refresh recovery, and recording absence in both
systems. Human transfer remains disabled until its independent prerequisites and
carrier-leg acceptance are complete. All implementation remains **UNVERIFIED**.
