# Account authentication and Neon — UNVERIFIED

DwellCall adapts the authentication source from the local HVACLine checkout:
scrypt password hashing, mandatory authenticator TOTP enrollment/verification,
recovery-code replacement, persisted rate limits, encrypted authenticator keys,
hashed challenge/session tokens and eight-hour revocable sessions. HVACLine was
read-only. Its users, database, credentials, agency model and booking data were
not imported. No installation, checks, database connections, migrations, services
or publication ran. Source and runtime behavior remain UNVERIFIED.

`/signup` → `/mfa` → `/account` creates an account without operator privileges.
Owner approval is required before dashboard, CRM, outbound controls or hero
conversations. This preserves the existing operator-only product boundary.
Approval uses an immutable account UUID; typing an operator's email does not grant
access. Signup does not verify email ownership. Email delivery, password reset,
SSO, tenant separation and an in-app role administration screen are not included
in the copied flow. The existing workspace remains shared by approved operators.

`/login` requires both a password and authenticator verification. Enrollment and
recovery show ten one-use recovery codes once; recovery requires verification of
a replacement authenticator before issuing a session. Five invalid MFA attempts
lock the factor for 15 minutes. Starting a new password challenge invalidates
older challenges. Password attempts share database limits of 30/minute globally
and five/15 minutes per normalized email. These limits span backend workers.

Sessions and challenges live in separate HttpOnly, SameSite=Strict cookies with
Secure and `__Host-` names in production. The web bridge keeps session tokens out
of JSON responses and checks origins before writes. Workspace/bridge access reads
account status, role, MFA version, session expiry and revocation from Neon.
Database failures deny access. Logout confirms database revocation before clearing
the session cookie. Legacy shared-password sessions no longer authorize access;
`DWELLCALL_OPERATOR_PASSWORD` and `DWELLCALL_SESSION_SECRET` are unused.

## Owner configuration

Use DwellCall's independent Neon project. The existing backend SQLAlchemy/psycopg
connection reads `DATABASE_URL` for the pooled runtime URL and
`DIRECT_DATABASE_URL` for the direct migration URL. Keep `sslmode=require` and
`DATABASE_SSL_MODE=require`. No second authentication database or Neon Auth service
is required. Existing environment files were preserved, and no connection was
attempted.

In the backend `.env`, configure:

- `ACCOUNT_AUTH_ENABLED=true` after installing dependencies and applying migrations.
- `ACCOUNT_PORTAL_SECRET`: a new random secret of at least 32 characters, different
  from `ADMIN_TOKEN` and provider secrets.
- `ACCOUNT_MFA_ENCRYPTION_KEY`: a new Fernet key. Keep a secure backup; replacing
  it without re-enrollment makes existing authenticators and recovery codes unusable.
- Retain `ADMIN_TOKEN`, `WEB_ORIGIN`, and all existing provider activation gates.

Generate the two new secrets locally and store them directly in environment
configuration; do not commit their values:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

In `apps/web/.env.local`, configure:

- `DWELLCALL_API_BASE_URL`: backend origin; HTTPS in production.
- `DWELLCALL_ACCOUNT_PORTAL_SECRET`: matches `ACCOUNT_PORTAL_SECRET`.
- `DWELLCALL_BACKEND_ADMIN_TOKEN`: matches the existing backend `ADMIN_TOKEN`.

These are server-only variables. Do not prefix secrets with `NEXT_PUBLIC_`.
The portal secret admits only account authentication endpoints; workspace calls
continue through the existing admin bridge after checking the account role.

## Owner commands

From the repository root using Python 3.13 and Node 24, install the adapted
cryptography and QR-code dependencies:

```bash
python -m pip install -e '.[dev]'
npm ci
```

After checking that the configured migration target is DwellCall's Neon database:

```bash
python -m alembic upgrade head
```

This applies all pending migrations, including new revision `20261105_0010`
(after `20261104_0009`). The authentication migration is forward-only to preserve
credentials, revocations and security evidence. Review pending migrations first.

Run the focused specifications and web checks:

```bash
python -m pytest tests/accounts
npm run test:web -- src/lib/operator-session.test.ts src/app/api/session/route.test.ts 'src/app/api/account/[action]/route.test.ts' src/app/api/ops src/app/api/homepage-chat
npm run typecheck:web
npm run lint:web
npm run build:web
```

For the database specifications, export `DWELLCALL_TEST_DATABASE_URL` pointing to a
separate disposable database, never the runtime or migration target. The existing
fixture creates and drops an isolated schema there:

```bash
python -m pytest tests/database/test_account_access.py
```

To exercise the UI, start these yourself in separate terminals:

```bash
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

```bash
npm run dev:web
```

## Owner approval and manual checks

1. Register with a password of at least 15 characters. Scan the DwellCall QR code
   or enter its manual setup key in an authenticator. Verify a code and save all
   ten recovery codes. Confirm the next screen says workspace approval is pending.
2. Confirm `/dashboard`, `/calls`, `/api/ops/*` and hero conversation starts remain
   inaccessible to this unapproved account. An email address alone must never
   grant workspace access.
3. To approve a trusted operator, use the DwellCall Neon SQL editor. Obtain its
   account reference from `/account` and confirm the intended person through a
   trusted channel. Replace the placeholder UUID below, then run deliberately:

   ```sql
   UPDATE accounts
   SET operator_access = true
   WHERE id = 'REPLACE_WITH_ACCOUNT_UUID'::uuid AND disabled_at IS NULL
   RETURNING id, operator_access;
   ```

   Refresh `/account`; confirm it opens the dashboard. Sign-in initiated with
   `?returnTo=conversation` should return to the homepage conversation card after
   approval. Existing conversation/provider gates and shared quotas still apply.
4. Sign out, then sign in again. A password alone must not open the workspace.
   Test an invalid/expired code, replay of an accepted code, challenge expiry,
   and five failed attempts. Invalid attempts must persist after refresh.
5. Use a saved recovery code after entering the password. Confirm existing
   sessions stop working immediately, replacement setup is required, new recovery
   codes appear, and used/old recovery codes cannot be reused.
6. Confirm browser JSON responses, local/session storage and logs contain no
   passwords, session/challenge tokens or backend credentials. Setup keys and
   recovery codes appear only in their deliberate security screens. Confirm
   HttpOnly/Secure/SameSite cookies and no-store responses in production.
7. Revoke operator access using the UUID below. Confirm the existing session
   loses workspace access on its next request. To disable the entire account,
   also set `disabled_at = now()`; re-enabling is an owner-managed database action.

   ```sql
   UPDATE accounts
   SET operator_access = false
   WHERE id = 'REPLACE_WITH_ACCOUNT_UUID'::uuid;
   ```

8. Confirm cross-origin sign-in/MFA/logout requests fail. Confirm backend/Neon
   outages deny workspace access and logout reports failure until revocation is
   confirmed. Check narrow-screen, keyboard, error and loading states.

Report results before treating authentication, migration or UI behavior as verified.
