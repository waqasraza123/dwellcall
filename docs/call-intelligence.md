> Current product scope: [focused outbound agent](outbound-agent.md) and
> [roadmap](roadmap.md). Qualification now concerns requested property needs and
> follow-up permission. Platform lead sales, lead inbox/task management, billing,
> listing discovery and browser conversations are parked extensions by default.
> Historical setup notes below do not expand the active product boundary.

# Outbound voice and platform lead qualification — UNVERIFIED

Owner requested HVACLine outbound reuse, ElevenLabs as the default, optional Retell,
and retained transcripts analyzed with OpenAI to identify possible platform leads.
HVACLine remained read-only. No credentials, environment files or accounts copied.
No checks, dependency installs, migrations, services or paid requests ran.

The existing shared audio guard, reservations, budgets, suppression, US allowlist,
operator MFA, signed events and uncertain-outcome recovery remain authoritative.
Human transfers stay permanently disabled. Calling requires a deliberate request;
there is no campaign, automatic dialing, redial or follow-up dispatch.

## Calling and qualification

`OUTBOUND_PROVIDER=elevenlabs` selects ElevenLabs SIP with Telnyx. No Retell or
external LLM credentials are required for that voice path. `OUTBOUND_PROVIDER=retell`
selects the existing Retell Custom LLM/SIP path with its existing credentials,
agent/version and WebSocket preflight. Browser voice remains its separate optional
Retell feature. Existing historical calls keep their provider when selection changes;
retain that provider's credentials and agent configuration for recovery.

`/calls` starts a real platform qualification conversation by default. The agent
explores professional role, current listing/lead workflow, CRM, needs, timing and
interest in a further conversation. The signed-in homepage dialog reuses HVACLine's
scenario selection, SMS verification, consent, saved request, polling and sign-in
continuation. That path is a fictional renting/buying/luxury demonstration; it can
never generate a real follow-up lead. Existing approved-operator access remains
required for both paths; this change does not enable arbitrary public calling.

Enable intelligence only after setting `OUTBOUND_INTELLIGENCE_ENABLED=true`,
`OPENAI_API_KEY`, `OUTBOUND_ANALYSIS_MODEL` (an owner-selected model supporting
Responses structured output), `OUTBOUND_QUALIFICATION_CRITERIA` (the actual platform
customer-fit rules) and `OUTBOUND_TRANSCRIPT_ENCRYPTION_KEY` (a separate stable
Fernet key). The model has no invented default or automatic fallback.
`OUTBOUND_TRANSCRIPT_RETENTION_DAYS` defaults to 30 (maximum 90).
`OUTBOUND_ANALYSIS_DAILY_LIMIT` defaults to 10 (maximum 50).

Consent version `dwellcall-ai-call-v2` discloses retained transcripts and OpenAI
analysis; old v1 consent cannot authorize new intelligence-enabled calls. There is
no audio recording. Voice identifies itself as AI and asks permission. The owner
must obtain explicit permission for transcript retention/analysis before submitting
on a recipient's behalf. When intelligence is disabled, no transcript is captured.

Completed, identity-verified provider events or deliberate reconciliation capture
only agent/user text. Both transcript and assessment are encrypted in Neon; raw
provider payloads, audio and tool details are not persisted. Data expires at the
original capture deadline, is hidden after expiry and is purged in batches of 100
through authenticated `POST /api/v1/outbound/transcripts/purge` with `{}`. The
owner must schedule/invoke that operation; no scheduler is installed. Retain the
encryption key until its data is purged; rotation/multi-key recovery is not included.

OpenAI uses the Responses API with `store=false`, strict structured output, a
bounded response, no tools and no automatic retry. The transcript is untrusted
evidence. Output includes disposition, needs, CRM, timing, unknowns, summary,
recipient quotes and suggested next step. Missing/unsupported permission quotes
fail analysis; follow-up classification requires expressed permission. Demo/mock
calls cannot qualify. Suppression overrides follow-up suggestions. These are
operator-review suggestions, not verified consent or automatic CRM activation.
The lead inbox on `/calls` shows the latest 100 unexpired completed assessments,
filterable by disposition, with links to the call and encrypted transcript view.

A committed analysis attempt precedes API access; duplicate final events do not
repeat successful analysis. Failed/incomplete/refused output stays failed. Deliberate
`POST /api/v1/outbound/calls/{id}/analyze` with `{}` can retry after 120 seconds,
up to three total attempts and the daily ceiling. No worker/background service is
started. The daily ceiling conservatively counts all attempts on rows attempted
today. Missing/empty/oversized or structurally incomplete transcripts stay unavailable;
they are never fabricated. Model decisions still require review against the transcript.

Official contracts: [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[ElevenLabs SIP outbound](https://elevenlabs.io/docs/api-reference/sip-trunk/outbound-call),
[post-call webhooks](https://elevenlabs.io/docs/eleven-agents/workflows/post-call-webhooks).

## ElevenLabs setup

Keep existing `.env` and Neon configuration. Extend backend configuration using
`.env.example`, without copying HVACLine keys, agents or phone numbers:

- `ELEVENLABS_API_KEY`, dedicated `OUTBOUND_AGENT_ID`, `OUTBOUND_PHONE_NUMBER_ID`,
  canonical `OUTBOUND_FROM_NUMBER` and separate `OUTBOUND_WEBHOOK_SECRET`.
- Existing allowlist/hash secret, US-only restrictions, positive cost/daily budget,
  destination/caller-ID confirmations and `OUTBOUND_PUBLIC_BASE_URL` remain required.
  `OUTBOUND_AGENT_VERSION` and `OUTBOUND_SIP_USERNAME` are Retell-only requirements.
- Import the authorized Telnyx SIP number into ElevenLabs with outbound trunk
  credentials, `sip.telnyx.com` (or the configured regional termination host), TLS,
  carrier destination/spending/concurrency/duration controls and recording disabled.
- Copy the exact `FIRST_MESSAGE` and `DEMO_PROMPT` from
  `apps/backend/src/dwellcall/telephony/outbound/prompt.py` into a dedicated agent.
  Preserve its dynamic variables. Only the native `end_call` system tool is permitted;
  no transfers, external tools, procedures, workflow, knowledge base or initiation hook.
  Set authenticated access, recording false, provider retention zero and maximum
  duration at most `OUTBOUND_MAX_DURATION_SECONDS` (180 by default).
- Configure signed post-call webhook
  `https://YOUR-API/api/v1/outbound-demo/webhook`, with transcript and initiation-failure
  events. Save its signing secret in `OUTBOUND_WEBHOOK_SECRET`. Redact logs and avoid
  logging request bodies, transcript views and WebSocket secret paths.
- Activate live calling only after owner acceptance, with `OUTBOUND_ENABLED=true`
  and mock false. Do not configure Retell to activate this provider.
- For the homepage dialog, set a dedicated `TELNYX_VERIFY_API_KEY` and
  `TELNYX_VERIFY_PROFILE_ID`, accept a real outbound call independently, then set
  `OUTBOUND_LIVE_VERIFIED=true` and `OUTBOUND_WEBSITE_ENABLED=true`. The recipient
  must be allowlisted, signed in with operator approval, verified by expiring SMS,
  and explicitly consenting. Codes have five attempts, bounded SMS quotas and
  cooldowns; verified challenges are consumed atomically with call reservation.

ElevenLabs `success` means dial accepted, not answered. Missing dial receipts hold
admission: use the provider dashboard and bind an existing conversation ID; there
is no automatic provider-wide lookup. Reconciliation requires agent, authorization,
caller and recipient evidence. Initiation failures missing complete identity keep
the slot unresolved for operator investigation. Stop marks the local request stopped;
for ElevenLabs it tells the operator to end the SIP call in Telnyx, then reconcile
or confirm all carrier legs ended. It does not claim the remote call was stopped.
Emergency pause blocks new calls; use carrier termination for active ElevenLabs calls.

Retell retains its existing provider setup in `docs/outbound-calling.md`. With
intelligence enabled, signed final webhook `transcript_object` or a retrieved final
transcript is captured when available; missing provider transcript evidence remains
unavailable. Its qualification turns use the existing OpenAI client with a separate
platform interview prompt. Retell demo/property turns keep the existing consultant.

## Owner commands (not executed)

From the repository root, Python 3.13 and Node 24:

```bash
python -m pip install -e '.[dev]'
npm ci
python -m pytest tests/outbound tests/test_retell.py tests/test_routes.py tests/test_graph.py tests/test_consultant_state.py
python -m pytest tests/database/test_outbound_calls.py tests/database/test_call_intelligence.py tests/database/test_audio_admission.py
npm run test:web
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m mypy
npm run typecheck:web
npm run build:web
```

Database specifications require the existing isolated fixture and a separate
`DWELLCALL_TEST_DATABASE_URL`; never point them at a live database. Review the
migration target and new `20261108_0012` migration before owner-only execution:

```bash
python -m alembic upgrade head
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

In a separate owner terminal: `npm run dev:web`.

Manual checks:

1. Leave live and intelligence off; exercise simulation, duplicate clicks, saved
   request recovery, unknown outcomes, suppression, US-only policy and quotas.
2. Verify anonymous/pending accounts cannot call or read transcripts. Sign-in/MFA
   should return to `/?demo_call=1`; another account cannot read a saved demo request.
   Expired/reused/wrong-number SMS challenges must not authorize calls.
3. After separate authorization for paid calls, preflight ElevenLabs, request one
   allowlisted consented call and verify disclosure, interruption, native hangup,
   three-minute cutoff, final signature/identity validation and carrier recovery.
4. Confirm ciphertext in database content columns, plaintext only in authorized
   transcript views, no transcript in logs and hidden/purged expired content.
5. Compare a real platform-interest call with a renter-only/demo call, explicit
   refusal, DNC request, uncertain answers and injected instructions. Inspect quoted
   evidence, unknowns and next-step suggestions. Demo and suppressed calls must
   never appear as follow-up leads. No CRM write or further call should occur.
6. Repeat signed final events: one capture/analysis. Exercise missing transcripts,
   OpenAI timeout/refusal/invalid JSON, explicit retry cooldown/ceilings and key-loss
   errors. Confirm the transcript remains recoverable after an analysis failure.
7. Select Retell explicitly, retain its pinned Custom LLM configuration and repeat
   qualification and transcript checks. Verify historical-provider recovery after
   switching selection and the existing browser voice flow separately.

All source, migration compatibility, provider behavior and UI remain **UNVERIFIED**
until the owner reports results. No deployment or provider activation was performed.

## Lead review and local tasks

The next source milestone adds deliberate approval/defer/reject decisions and local
follow-up tracking. Setup and unexecuted acceptance commands:
[Reviewed platform leads and follow-up tasks](call-lead-reviews.md). Migration 0013
is unapplied; this milestone remains UNVERIFIED.
