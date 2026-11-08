# Reviewed platform leads and follow-up tasks — UNVERIFIED

The next step after transcript qualification adds approve/defer/reject decisions,
an action history and local follow-up tasks on `/calls`. It reuses existing Neon,
account MFA, transcript encryption, suppression, call evidence and request recovery.
No new credentials or providers are introduced. Migration `20261108_0013` is written
but unapplied. No tests, builds, checks, services, migrations or live calls ran.

## Behavior

Open a potential lead or task, inspect its transcript and quoted permission, then
explicitly confirm that evidence before approving. Approval records a fingerprint
of the current assessment; it does not change the AI's assessment. Only completed
real qualification calls with current transcript-analysis consent, an unexpired
retained assessment, recipient evidence, explicit follow-up permission and an
allowlisted unsuppressed number may be approved or scheduled. Demo/mock calls,
expired/missing evidence and suppressed recipients remain blocked.

A separate deliberate action schedules one local task with a due date. Dates must
include a timezone, be in the future, fall within 90 days and precede the evidence's
expiry. The browser displays local time and submits UTC. Open tasks are shown in
due order, with an overdue label in the review. The task list supports open,
completed, cancelled and deferred views (up to 100 each). Deferring can include a
review-reminder date; rejection or deferral cancels an open task.

Record an outcome only after observing it: contacted, no answer, not interested,
do not contact or closed. Completion records evidence of that operator action;
it does not make a call. A do-not-contact outcome also creates durable suppression.
Not-interested, closed and do-not-contact outcomes reject the lead. A fresh approval
is required before another task can be scheduled after completion or cancellation.

Approval remains historical when evidence expires or suppression changes. Reads
recompute eligibility and task actionability; a previously approved task becomes
blocked. An operator can still cancel or close it. A reminder is not fresh outreach
consent; recheck the recipient's current permission before any future contact.
There is no task worker, scheduler, automatic phone call, CRM export or notification.
Existing deliberate outbound call controls remain separate.

## Authentication and recovery

New backend routes under `/api/v1/account/call-leads` reuse the existing account
portal key and a current MFA-verified bearer session. Owner-approved operator
access is required. The shared admin token alone does not authorize these routes.
The server resolves the actor from the session; request bodies cannot choose it.
The browser bridge is `/api/call-leads/...`, with origin checks and a narrow route
allowlist. No token is exposed in browser responses or action payloads.

Endpoints:

- `GET /{call_id}`: current decision, task state, eligibility blockers and 25 recent
  action references.
- `POST /{call_id}/actions`: `request_id`, `expected_version`, `action`,
  `evidence_reviewed`, optional `due_at` and `outcome`.
- `GET /tasks?status=open|completed|cancelled|deferred`: at most 100 tasks.

Actions are serialized by the existing shared guard and call row. A committed
request ID can be replayed without another mutation. Reusing it for different
content or another actor/call is rejected. Version checks reject stale decisions.
The browser saves the action key and non-content action fields before sending;
a lost response requires refreshing history or retrying that same saved action.
No transcript, assessment, personal notes or credential is put in recovery storage.

The database retains account references, action hashes, versions, dates, typed
outcomes and state transitions for audit. It stores no additional transcript or
free-text notes. Transcript/assessment expiry and purge continue to use the existing
call-intelligence retention controls. Review/action evidence is retained separately.

## Owner commands (not executed)

With the existing project environment, from the repository root:

```bash
python -m pytest tests/outbound/test_lead_review_schemas.py tests/outbound/test_lead_review_routes.py
python -m pytest tests/database/test_call_lead_reviews.py tests/database/test_call_intelligence.py tests/database/test_outbound_calls.py
npm run test:web -- src/features/outbound/review-api.test.ts 'src/app/api/call-leads/[[...path]]/route.test.ts'
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m mypy
npm run typecheck:web
npm run build:web
```

Database tests require the existing disposable `DWELLCALL_TEST_DATABASE_URL`
configuration. Review migration 0013 and the target before owner execution:

```bash
python -m alembic upgrade head
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

Use a separate owner terminal for `npm run dev:web`.

Manual checks:

1. Anonymous, unapproved, revoked-session and shared-admin-only requests must not
   read or modify lead reviews. Cross-origin writes must be rejected.
2. Review a real eligible transcript. Approval must require the evidence checkbox;
   schedule a due task separately. Confirm there is no provider/CRM request.
3. Replay one action, double-click and retry after an interrupted response: one
   decision/version/event. Submit a stale version from a second tab: conflict.
4. Reject/defer an approved open task: it is cancelled; a deferral date appears in
   the deferred view. Complete/cancel tasks, inspect history, and require a fresh
   approval before another task is scheduled. Check dates across timezones.
5. Suppress the number, remove it from the allowlist or expire/purge its evidence:
   historical approval remains visible, but scheduling/actionability is blocked.
   Demo/mock calls and unsupported permission quotes must never qualify.
6. Record do-not-contact: verify durable suppression and rejected lead state.
   Record no-answer: no automatic retry. Refresh task and lead views explicitly.

Implementation remains **UNVERIFIED** until the owner reports execution results.
