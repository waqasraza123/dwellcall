# Hero voice and text chat — UNVERIFIED

The homepage adapts HVACLine's `homepage-chat.tsx`, chat composer, private server
bridge and connection/recovery patterns. Its olive/ivory card, house illustration,
scenario selector and typography are DwellCall-specific. HVACLine was read-only.

Existing operator sign-in returns to the hero. Both live modes require explicit AI
and fictional-data consent. Text reuses the property consultant/LangGraph; voice
uses the separately pinned Retell web agent and existing Custom LLM WebSocket.
No phone number, telephone dialing, CRM export, appointment or transfer is involved.
US catalog defaults remain authoritative; the existing CRM/listing UI remains.
Human transfers are permanently unavailable. Human requests receive a fixed
explanation that DwellCall is an AI-native voice platform operated only by AI
agents; this also applies to browser text and simulation.

Migration `20261104_0009` adds browser ownership/admission/turn evidence linked to
the existing audio reservation. Voice/text/phone share the global slot and daily
conversation budgets. No transcripts, replies or access grants are stored in this
table. Text continuity uses a signed, browser-memory state token; only the request
ID persists in session storage. Refresh recovers status and end controls, without
reconnecting audio or replaying messages. Keep the admin signing token stable
while sessions are active. Lost provider outcomes remain reserved for lookup/stop;
an empty lookup never creates another call. Interrupted text turns cannot replay.

## Owner configuration

Backend: keep `BROWSER_TEXT_ENABLED=false`, `BROWSER_VOICE_ENABLED=false` initially.
For development simulation set `BROWSER_MOCK_ENABLED=true`; no provider/LLM requests
or microphone capture occur. Simulation cannot be combined with live browser modes
or production. It still requires the existing database, strong `ADMIN_TOKEN`,
positive `CONVERSATION_RESERVED_COST_CENTS` and adequate
`CONVERSATION_DAILY_BUDGET_CENTS`. Reserve the maximum cost of a whole conversation,
including up to `CONVERSATION_MAX_RESPONSES` model turns. No budget refund occurs.

Live text: `BROWSER_MOCK_ENABLED=false`, `BROWSER_TEXT_ENABLED=true`, configured
`LLM_API_KEY`/`LLM_MODEL` and existing consultant catalog/business settings.

Live voice additionally requires `BROWSER_VOICE_ENABLED=true`,
`RETELL_TEST_AUDIO_ENABLED=true`, `RETELL_API_KEY`, separately pinned
`RETELL_AGENT_ID`/numeric `RETELL_AGENT_VERSION`, and `RETELL_WEBSOCKET_SECRET`.
Publish that Custom LLM agent with the HTTPS backend's WSS URL, matching signed
lifecycle webhook, `basic_attributes_only`, retention of 1–7 days, no contact
memory/session tools, and duration within `CONVERSATION_MAX_DURATION_SECONDS`.
Backend hosting must support WebSockets. Browser audio requires HTTPS or localhost.
The pinned browser SDK consumes the provider-declared gateway transport and ICE
servers; provider API keys remain backend-only. References:
[Retell web calls](https://docs.retellai.com/deploy/web-call),
[creation contract](https://docs.retellai.com/api-references/create-web-call).

Frontend environment is unchanged: `DWELLCALL_API_BASE_URL`,
`DWELLCALL_BACKEND_ADMIN_TOKEN`, `DWELLCALL_OPERATOR_PASSWORD`,
`DWELLCALL_SESSION_SECRET`. No new browser-exposed secrets are needed.

## Owner validation

Nothing was executed. From the repository root, with the existing Python 3.13
environment, Node 24 and an isolated `DWELLCALL_TEST_DATABASE_URL`:

```bash
npm ci
python -m pytest tests/conversations tests/test_routes.py tests/test_retell.py tests/test_graph.py tests/outbound
python -m pytest tests/database/test_browser_conversations.py tests/database/test_audio_admission.py tests/database/test_outbound_calls.py
npm run test:web -- src/features/homepage-chat/api.test.ts 'src/app/api/homepage-chat/[[...path]]/route.test.ts' 'src/app/api/ops/[...path]/route.test.ts'
npm run typecheck:web
npm run build:web
```

After reviewing the database target, owner-only: `python -m alembic upgrade head`.
Then start the existing API/web services in separate owner terminals:
`python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000` and
`npm run dev:web`.

Manual checks: inspect desktop/mobile hero and keyboard focus; switch tabs and
scenarios; sign in and return; check consent and disabled modes; simulate text
turns, Enter/Shift+Enter, retained drafts, double-click, refresh/recovery and end;
check shared quotas/pause with `/calls`. Once separately authorized for paid
services, check live text across renting/buying/luxury and live voice permission
denial, connection, mute/unmute, audio playback, interruption, end during startup,
refresh microphone release, timeout and final webhook/reconciliation. Confirm
that anonymous visitors cannot start sessions and one browser cannot access
another browser's session. All runtime/security/rendering behavior is UNVERIFIED.
