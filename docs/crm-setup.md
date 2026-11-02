# Optional CRM setup — implementation UNVERIFIED

The adapter and executable specifications are now written at the owner's request.
They have not been executed. Core Test Audio acceptance remains pending. Keep
`CRM_PROVIDER=none` and `CRM_SYNC_ENABLED=false`; the default API mounts no CRM
routes, creates no FUB client and needs no CRM database tables or credentials.
The Retell graph does not call CRM. No `.env` values were changed by Codex.

## Owner checks

From the repository root with the Python 3.13 virtual environment active:

```sh
python -m pip install -e '.[dev]'
python -m pytest tests/crm
python -m pytest tests --ignore=tests/database
python -m ruff check apps/backend/src tests migrations
python -m ruff format --check apps/backend/src tests migrations
python -m mypy
```

These are owner commands, not previously reported successes. The new ordinary
CRM specifications use synthetic settings and `httpx.MockTransport`; no real CRM
traffic is needed. The added dependency `email-validator` reuses HVACLine's existing
contact-validation dependency. No lockfile/resolution or compatibility claim is made.

Database specifications use the shared isolated-schema fixture adapted from the
existing DwellCall admission tests. Privately export a separate
`DWELLCALL_TEST_DATABASE_URL`, with independent runtime URLs in ignored `.env`, then:

```sh
python -m pytest tests/database/test_crm.py tests/database/test_audio_admission.py
```

The fixture requires schema creation permission and drops only its unique test
schema. It does not run migrations or touch runtime tables. These specifications
cover transaction replay/races, durable delivery, crash recovery, permission
revocation, destination changes, throttling and expiry with a mocked provider.
They do not establish migration or real-account automation correctness.

## Optional schema and credentials

Review unapplied migration `20261103_0002_optional_crm.py`. It adds only export
evidence, opaque audit events and a shared dispatch-delay row. After separately
approving the write to the independent DwellCall Neon target, the owner can run:

```sh
python -m alembic upgrade head
python -m alembic current
```

`head` now includes both the initial audio schema and optional CRM schema. No
migration runs at startup; `none` works without the second revision. Downgrade
refuses to delete existing CRM consent/delivery evidence.

Follow the [official registration/authentication guide](https://docs.followupboss.com/docs/start-here-brand-new-integration)
to obtain an independent account API key and registered system name/key. Credentials
are backend-only. Do not register/change an account as part of an implementation
session without authorization. The adapter uses Basic API-key username/empty password,
registered system headers, a pinned HTTPS events URL, no redirects and no implicit
retries. No FUB key was inspected, copied or transmitted during implementation.

`.env.example` includes the following disabled defaults; preserve the real `.env`:

```dotenv
CRM_PROVIDER=none
CRM_SYNC_ENABLED=false
CRM_OWNER_APPROVED=false
CRM_CORE_VOICE_VERIFIED=false
CRM_AUTOMATIONS_DISABLED_VERIFIED=false
CRM_HASH_SECRET=
CRM_RETENTION_DAYS=7
CRM_MAX_ATTEMPTS=3
FOLLOWUPBOSS_API_KEY=
FOLLOWUPBOSS_SYSTEM_NAME=
FOLLOWUPBOSS_SYSTEM_KEY=
FOLLOWUPBOSS_LEAD_SOURCE=DwellCall Demo
```

Use an independent random hash secret of at least 32 characters. It binds approved
payloads/destinations without storing raw keys in delivery rows. Changing it,
credentials, business name or source changes the destination binding and prevents
old queued work from dispatching. A changed destination requires a newly confirmed
version and separate permission, not a replay of the old request.

## Permission and local authorization

After the optional schema/configuration is ready, selecting `followupboss` with
sync still off exposes authenticated administrative endpoints. It requires complete
CRM credentials and a strong existing `ADMIN_TOKEN`; nothing sends until dispatch
is separately enabled. All endpoints require `X-Admin-Token`:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/crm/admin/destination` | Obtain the opaque configured destination, business name and dispatch state. |
| `POST /api/v1/crm/admin/exports` | Persist a confirmed snapshot and separate permission after an admitted call has finalized. No HTTP call to CRM. |
| `GET /api/v1/crm/admin/exports/{id}` | Minimal status only, without contact/summary payloads. |
| `POST /api/v1/crm/admin/exports/{id}/revoke` | Revoke permission, clear local personal payload and cancel unsent work. A dispatched request cannot be retracted. |
| `POST /api/v1/crm/admin/exports/{id}/reconcile` | Resolve an unknown result using `delivered` plus verified person ID, or `do_not_retry`, and an opaque evidence reference. Never resends. |
| `POST /api/v1/crm/admin/dispatch/resume` | Resume a credential-paused destination after operator review, with an opaque evidence reference. Failed/unknown exports are not requeued. |

The [synthetic request template](examples/crm-export.example.json) illustrates the
schema. Its placeholder destination/call must fail authorization. Its `true` flags
are schema examples, not evidence that any real person granted permission.
An operator must witness/record confirmation of the selected information and
separate storage/FUB permission naming the business, destination and purpose before
submitting a real snapshot. Use an opaque evidence reference; never a transcript
or personal details in that field. The server timestamps this operator attestation.
No model tool or unauthenticated caller can set these permissions through voice.

Only ended, admitted calls belonging to the configured Retell agent qualify;
unresolved calls and unadmitted terminal webhook tombstones do not. Same call/version
and identical authorization replay the existing status; changed data/permission with
that version conflicts. A newer confirmed version cancels pending older versions.
Uncertain/in-flight outcomes block new versions across destination changes until
reconciled. Repeated authorization never extends permission expiry or revives sent,
revoked, failed or uncertain work. The current graph still supports rentals only;
accepting other scenario names in the CRM schema does not implement Phase 2 voice.

## Worker and real activation

Before enabling dispatch, obtain separate owner approval, core conversation
acceptance, and real validation that the approved demo destination cannot trigger
campaigns, messages, action plans or downstream automations for either new or
existing contacts. FUB [inquiry events can trigger existing rules](https://docs.followupboss.com/reference/events-post).
Omitting campaign fields does not suppress them. The three verification/approval
flags are owner attestations, not implemented proof or permission to skip validation.
Never send real personal information without the separate snapshot permission.

Only after those conditions are met may the owner set the three approval/verification
flags and `CRM_SYNC_ENABLED=true`. A separately authorized bounded worker invocation
can then send queued approved work:

```sh
python -m dwellcall.crm.jobs
```

This command can perform real writes when dispatch is enabled; it was not executed.
The batch is bounded to 20 seconds/12 candidates and creates no background process.
Repeated invocation/scheduling is owner-controlled. No new queue service is required.
With defaults it exits disabled without touching a database or provider. A shared
advisory lock serializes worker batches; row locks are released before HTTP I/O.
429 delays persist across batches/jobs. Sending crashes and ambiguous POST outcomes
become unknown and are never automatically resent. Contact deduplication is not
event idempotency; an absent remote search result is not proof of non-delivery.
401/403 pauses the destination, preventing repeated submissions from other pending
jobs until credentials change or an operator explicitly resumes it after review.

Payloads are cleared after confirmed delivery/permanent failure/ignored source,
revocation or expiry. Metadata remains for deduplication and audit. Retention
maintenance needs owner-run jobs; it is not a database TTL. To run bounded local
expiry/crash recovery while CRM dispatch is disabled, the owner can separately
authorize the database-only command:

```sh
python -m dwellcall.crm.jobs --purge-only
```

It processes at most 50 eligible records per invocation and sends no HTTP. Repeat
or schedule as needed to honor retention even after selecting `none`. It requires
the optional schema. Reconciliation records a reviewed outcome, not permission for
another POST. See [design and official references](follow-up-boss.md) for details.
