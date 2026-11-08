# Focused outbound agent — owner setup and acceptance

The active product is one requested property callback plus transcript and summary.
README and [roadmap](roadmap.md) define the current scope. Source is **UNVERIFIED**;
no tests, builds, installs, migrations, services, provider calls or deployment ran
for this trim. Existing environment files and provider settings are untouched.

## What to configure

Keep `PLATFORM_EXTENSIONS_ENABLED=false` on the backend and
`DWELLCALL_PLATFORM_EXTENSIONS_ENABLED=false` on the frontend. These defaults park
listing/agent discovery, CRM administration, billing, browser conversations and
lead-review/task management. Enabling extensions restores old routes and workspace
sections, subject to their existing feature/auth gates. It does not restore the old
homepage, activate providers, grant roles or authorize paid work.

Use the existing independent Neon database and account/MFA setup in
[authentication.md](authentication.md). Frontend server configuration remains
`DWELLCALL_API_BASE_URL`, `DWELLCALL_BACKEND_ADMIN_TOKEN` and
`DWELLCALL_ACCOUNT_PORTAL_SECRET`; backend authentication uses `ADMIN_TOKEN`,
`ACCOUNT_AUTH_ENABLED`, `ACCOUNT_PORTAL_SECRET`, `ACCOUNT_MFA_ENCRYPTION_KEY` and
`WEB_ORIGIN`. Approved accounts land on `/calls`; the old `/dashboard` redirects
there. Old discovery/review/CRM routes return not found in the focused scope.
Pricing redirects home and billing redirects to the call workspace.

Follow the ElevenLabs/SIP configuration in [call-intelligence.md](call-intelligence.md):
`OUTBOUND_PROVIDER=elevenlabs`, a dedicated agent, SIP phone ID/caller, separate API,
webhook/hash secrets, authorized US allowlist, destination/caller-ID confirmation,
public API origin and positive per-call/daily spending reservations. Retell needs
its separate pinned agent/version, WebSocket and LLM setup only if selected.
The backend's existing `LLM_API_KEY` powers Retell conversation turns;
`OPENAI_API_KEY` powers post-call analysis. No Stripe or listing API account is
needed for this core workflow.

For transcripts/results, configure the existing
`OUTBOUND_INTELLIGENCE_ENABLED`, `OUTBOUND_TRANSCRIPT_ENCRYPTION_KEY`,
`OPENAI_API_KEY`, `OUTBOUND_ANALYSIS_MODEL`, `OUTBOUND_QUALIFICATION_CRITERIA`,
retention and analysis-attempt limits. Criteria should describe stated property
needs, timing, expressed interest and permission for further contact. They should
not ask whether the recipient wants to buy DwellCall subscriptions. Owner supplies
the actual criteria/model; the app does not invent a business offer.

**Agent prompt update required:** the dedicated ElevenLabs agent must use the
current exact `FIRST_MESSAGE` and `DEMO_PROMPT` from
`apps/backend/src/dwellcall/telephony/outbound/prompt.py`. The previous prompt tried
to qualify customers for the DwellCall platform. Preflight will reject that old
configuration before dialing. No remote prompt/agent was changed by this work.

With live calling off, development simulation remains available through existing
`OUTBOUND_MOCK_ENABLED` configuration and uses no voice/LLM provider requests.
It exercises requests/status/recovery; it does not fabricate recorded transcripts
or completed OpenAI assessments. Enable real calling/analysis only after separate
owner setup and consented acceptance. The homepage SMS demo remains separately
gated by its existing verification credentials and live-acceptance flags.

## Current operational boundaries

- The operator screen makes a real qualification call; the homepage demonstration
  is fictional and never becomes a real lead. Neither has live inventory or booking.
- Every call remains deliberate, allowlisted, US-only, bounded and consented.
  Human transfers are permanently disabled. Requests for a person receive the
  existing AI-only explanation.
- Post-call summaries are suggestions supported by recipient words. They do not
  create CRM records, appointments, follow-up tasks or further calls in core mode.
- Stop during conversation uses the agent's native termination behavior. Operator
  termination for ElevenLabs requires ending the SIP call in Telnyx, followed by
  reconciliation/carrier completion confirmation. Pause blocks new calls.
- Transcript access expires at the existing deadline. The owner still needs to
  invoke/schedule the bounded purge endpoint; no scheduler is installed.
- Existing tables, migrations, historical calls, encrypted data and durable
  suppression remain. Apply reviewed migration history normally; do not drop old
  tables to trim the product. Existing listing suppression is still respected.
- Earlier assessments are historical; this refocus does not rewrite them, repeat
  paid analysis or change their evidence. Evaluate the new prompts on new calls.

## Owner commands — not executed

Use Python 3.13/Node 24 and the existing project environment. From repository root:

```bash
python -m pytest tests/test_product_scope.py tests/outbound tests/test_retell.py tests/test_routes.py tests/test_graph.py
python -m pytest tests/database/test_outbound_calls.py tests/database/test_call_intelligence.py tests/database/test_audio_admission.py
npm run test:web -- src/lib/product-scope.test.ts src/lib/bridge-policy.test.ts src/features/outbound 'src/app/api/ops/[...path]/route.test.ts' 'src/app/api/billing/[action]/route.test.ts' 'src/app/api/homepage-chat/[[...path]]/route.test.ts' 'src/app/api/call-leads/[[...path]]/route.test.ts' src/app/api/stripe/webhook/route.test.ts
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m mypy
npm run typecheck:web
npm run build:web
```

Database specifications require the existing isolated-fixture configuration and
separate disposable `DWELLCALL_TEST_DATABASE_URL`. Install dependencies only if
needed using `python -m pip install -e '.[dev]'` and `npm ci`. This trim adds no
dependencies or migration. Existing unapplied revisions still need owner review
before `python -m alembic upgrade head` against the intended database.

Owner-only service commands, if needed for manual acceptance:

```bash
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
npm run dev:web
```

Use separate terminals for those services. No process was started by Codex.

## Manual acceptance

1. With both extension flags false, visit `/`, sign in/MFA and open `/calls`.
   Confirm the homepage explains the phone workflow, the sidebar contains calls
   and demo access, and no pricing/listings/browser chat/task UI is active.
2. `/dashboard` redirects to `/calls`. Direct listings/CRM/review workspace URLs
   and extension API bridges must not expose the parked modules. Verify direct
   backend extension routes are also unavailable. Approved accounts should not
   land on the old dashboard or a subscription checkout.
3. In simulation, submit once, double-click, reload mid-request, inspect history,
   reconcile an unknown receipt, suppress a number and pause/resume new requests.
   No provider call or invented transcript should appear.
4. After separately authorizing paid acceptance, use the current published prompt
   and one consented allowlisted call. Check property questions, timing, correction,
   interruption, stop/DNC, wrong number, silence, voicemail and duration ceiling.
5. Confirm signed final events attach the right call and retain the authorized
   encrypted transcript. Compare summary/needs/timing/permission/quotes with what
   was actually said. Missing facts must remain unknown; no DwellCall sales pitch.
6. Test invalid signatures, duplicated final events, missing transcript, analysis
   failure/retry, expiry/purge and uncertain dial/carrier recovery. Confirm no redial,
   booking, CRM export or future contact occurs.
7. If restoring extensions deliberately, set both flags true and repeat their
   separate owner acceptance guides. The opt-in does not imply those features work.

Report results before calling the showcase verified or making performance claims.
