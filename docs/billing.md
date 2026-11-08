# Stripe pricing and account subscriptions — UNVERIFIED

Adapted from the local read-only Quantrift project at
`/Users/mc/development/AI/AI-Agents/quantrift.live`. DwellCall keeps its existing
Next.js/FastAPI/SQLAlchemy/Neon architecture and MFA account sessions. No Quantrift
Stripe keys, price IDs, customer data, database URLs or hosting configuration were
copied. No installation, verification, migrations, services, provider setup,
checkout, charges, commits, pushes or deployments were executed.

| Plan | USD / month |
| --- | ---: |
| Free | 0 |
| Pro | 29 |
| Team | 79 |

The homepage and `/pricing` read one backend catalog. `/billing` displays the
signed-in account's subscription, resumes checkout, refreshes confirmed status,
and opens the Stripe customer portal for invoices, payment methods, plan changes
and cancellation. Signup/login/MFA preserve the selected plan. Checkout requires
an MFA-authenticated account with owner-approved operator access. Billing requests
never use an admin credential or accept a client-selected account/customer ID.

This is a pricing and billing adaptation. Subscriptions belong to individual
DwellCall accounts. Quantrift's tenant memberships, invitations, five Team seats,
AI credit accounting and legacy transition grants are not copied. No new usage
paywall is introduced. Payment does not promote an account, activate a provider,
change call quotas, grant outreach permission or create a private workspace.
Plan-specific product entitlements remain separate implementation work before
selling differentiated usage or team access. The public pricing copy does not
promise those unimplemented allowances. Existing shared workspace boundaries and
permanent AI-only operation remain.

## Reused source

- `billing/catalog.py`: Free/Pro/Team keys and monthly amounts; DwellCall copy.
- `billing/gateway.py`: Stripe SDK, hosted Checkout, price validation, mode
  separation, hosted portal selection and signature verification. Adapted to
  synchronous FastAPI worker threads, account identities and DwellCall metadata.
- `billing/portal.py` and catalog setup CLI: stable product/price lookup keys and
  three portal configurations; independent DwellCall names and identifiers.
- `billing/service.py`, state/models and pricing components: adapted reservation,
  reconciliation, webhook receipt and presentation patterns. DwellCall uses its
  existing sync sessionmaker and a bounded owner-operated reconciliation command.

## Owner configuration

Use Stripe Python `16.1.0` and snapshot API version `2026-10-28.endive`, matching the
source integration. All Stripe configuration lives in the backend `.env`:

```dotenv
BILLING_ENABLED=false
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRODUCT_ID=dwellcall_subscription_v1
STRIPE_PRO_PRICE_ID=
STRIPE_TEAM_PRICE_ID=
STRIPE_PORTAL_CONFIGURATION_ID=
STRIPE_PORTAL_PRO_CONFIGURATION_ID=
STRIPE_PORTAL_TEAM_CONFIGURATION_ID=
STRIPE_LIVE_MODE=false
```

Begin with DwellCall-specific sandbox credentials and a separate development Neon
database. Retain `DATABASE_URL` (pooled), `DIRECT_DATABASE_URL` (direct),
`WEB_ORIGIN` and the configuration in [authentication.md](authentication.md).
Production billing requires an HTTPS `WEB_ORIGIN`. Test/live keys must match
`STRIPE_LIVE_MODE`; a customer binding cannot switch modes. Use a separate live
billing database rather than repurposing records from sandbox.

`STRIPE_PRODUCT_ID` defaults to `dwellcall_subscription_v1` when omitted. To use
an existing manually created product, set it to that product's `prod_...` ID and
set `STRIPE_PRO_PRICE_ID` and `STRIPE_TEAM_PRICE_ID` to its existing prices in the
same Stripe account and mode. Both prices must be active, USD, recurring every
one month, at 2900 and 7900 cents respectively. Setup retrieves and validates
explicit price IDs without requiring lookup keys or modifying those prices.
Checkout and subscription reconciliation validate the configured product ID.

The web app uses its existing `DWELLCALL_API_BASE_URL` and
`DWELLCALL_ACCOUNT_PORTAL_SECRET`; no Stripe secrets or price IDs belong in
`NEXT_PUBLIC_` variables. No new frontend dependency is required.

## Owner commands

From the repository root with Python 3.13 and Node 24:

```bash
python -m pip install -e '.[dev]'
npm ci
```

Review pending migrations and the target database, then apply them yourself:

```bash
python -m alembic upgrade head
```

New forward-only revision `20261105_0011`, after authentication revision 0010,
adds account billing records, durable checkout reservations and webhook receipts.
No existing account is charged, granted privileges or assigned a subscription.

With a DwellCall sandbox key configured and billing still disabled, this command
creates or reuses the DwellCall product, monthly Pro/Team prices, and three portal
configurations. It writes to Stripe when **you** run it:

```bash
python -m dwellcall.billing.cli setup
```

Store the five returned price/configuration IDs in the backend environment.
Setup retrieves `STRIPE_PRODUCT_ID`; a missing `prod_...` product fails for owner
review rather than creating a replacement. The default custom product can still
be created on first setup. Explicitly configured price IDs take precedence over
the managed `dwellcall_pro_monthly_v1` / `dwellcall_team_monthly_v1` lookup keys.
When neither an explicit ID nor a managed lookup match exists, setup creates a
price, so configure both existing price IDs before setup to avoid duplicates.
Creation idempotency keys include the product ID. Existing incompatible prices,
a mode mismatch, or an archived product require owner review.

The management portal handles invoices, payment details and period-end
cancellation. The Pro portal offers Team as its upgrade target; the Team portal
offers Pro as its downgrade target. Upgrades invoice prorations immediately;
decreasing-price changes are scheduled for period end. Each portal catalog has
one monthly target price for the shared product, as in Quantrift.
All three configurations record the configured product in metadata; management
keeps plan changes disabled, while Pro and Team target that product's prices.

Register a snapshot webhook destination on the final HTTPS hostname, without a
redirect, using either:

- Web origin: `/api/stripe/webhook`.
- Backend origin: `/api/v1/billing/webhook`.

Use `2026-10-28.endive` and subscribe to:

```text
checkout.session.completed
checkout.session.expired
customer.subscription.created
customer.subscription.updated
customer.subscription.deleted
customer.subscription.paused
customer.subscription.resumed
invoice.paid
invoice.payment_failed
invoice.payment_action_required
```

Store the destination signing secret in `STRIPE_WEBHOOK_SECRET`. Then enable
`ACCOUNT_AUTH_ENABLED=true` and `BILLING_ENABLED=true` with all required settings,
and restart your processes yourself. Setup does not register or enable webhooks.

Webhook handlers verify original bytes/signatures and sandbox/live mode, then
persist bounded event references with a unique event ID. They acknowledge durable
receipts without making Stripe requests or storing raw event/card data. Duplicate
or reordered events trigger retrieval of the current subscription, not replay of
an old plan. Unknown prices, mismatched ownership, multiple subscriptions,
unpaid invoices and expired periods cannot project a paid plan. Redirect query
parameters never confirm a purchase.

Refresh billing from the UI, or run this bounded one-shot command to drain
pending updates and refresh stale records:

```bash
python -m dwellcall.billing.cli reconcile --max-accounts 25
python -m dwellcall.billing.cli reconcile --account-id ACCOUNT_UUID
```

No worker or scheduler is started or installed. For unattended updates, arrange
an owner-managed schedule for this command after sandbox acceptance; successful
records move to the back of the oldest-synchronized-first batch. Pending receipts
and last synchronization are visible on `/billing`. Diagnose a failing account
before repeatedly scheduling a batch that stops on its error.

## Unknown-result recovery

Customer and checkout reservations commit to Neon before remote creation. Account
row locks serialize competing requests. Same-plan retries recover the existing
checkout; changing plans expires a verified open checkout first. A completed
checkout waits for its subscription to appear. Existing subscriptions use the
portal instead of another checkout. Retrying an unknown create uses its original
idempotency key for at most 23 hours; older unknown creates block instead of being
recreated after Stripe's idempotency retention window.

If a create succeeded remotely but its result was lost beyond that window,
inspect the DwellCall account UUID, checkout request reference and Stripe metadata
in the Stripe dashboard. These owner-only commands bind a verified existing
object; they create no remote object:

```bash
python -m dwellcall.billing.cli bind-customer --account-id ACCOUNT_UUID --customer-id cus_EXISTING
python -m dwellcall.billing.cli bind-checkout --request-id REQUEST_UUID --session-id cs_EXISTING
python -m dwellcall.billing.cli reconcile --account-id ACCOUNT_UUID
```

Customer/checkout identity, plan metadata and mode must match. Bindings cannot
replace another confirmed object. Never clear reservations or retry with a fresh
identity merely because a provider lookup is unavailable. If no verified object
can be found, retain the reservation for owner investigation.

## Owner verification

No commands below have been run:

For the configurable product change, run the isolated mocked specifications
(no database connection or Stripe API calls):

```bash
python -m pytest tests/billing/test_catalog.py tests/billing/test_gateway.py tests/billing/test_portal.py
```

These cover the legacy default, `.env` and environment overrides, manually
configured products/prices without duplication, rejection of invalid product IDs,
missing generated products, incompatible prices, checkout/reconciliation product
and mode validation, and all three portal configurations. Manually review the
backend product/price IDs together in the same Stripe sandbox; Free remains local
and both paid prices must belong to the configured product. No Stripe setup
command is needed to run these mocked specifications.

Broader owner acceptance commands:

```bash
python -m pytest tests/billing tests/accounts
npm run test:web -- src/features/billing 'src/app/api/billing/[action]/route.test.ts' src/app/api/stripe/webhook/route.test.ts src/lib/operator-session.test.ts src/app/api/account
npm run typecheck:web
npm run lint:web
npm run build:web
```

With `DWELLCALL_TEST_DATABASE_URL` exported for a separate disposable database,
using the existing isolated-schema fixture:

```bash
python -m pytest tests/database/test_billing.py tests/database/test_account_access.py
```

Start local services yourself in separate terminals when ready:

```bash
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

```bash
npm run dev:web
```

Manual acceptance:

1. Confirm Free/$29/$79 prices match on the homepage, `/pricing`, `/billing` and
   the sandbox Checkout page. Disabled billing must show unavailable checkout.
2. Follow a paid plan through signup, MFA and owner approval. Anonymous,
   unapproved, revoked and disabled accounts must never purchase or view another
   account's billing. A backend admin token alone must not authorize billing.
3. Complete sandbox checkout, including payment authentication. Returning with
   `checkout=success` must not itself change the plan. Deliver the webhook, then
   refresh/process reconciliation and confirm the actual paid plan and dates.
4. Test failed payment, incomplete checkout, canceled checkout, expired checkout,
   repeated clicks, concurrent requests, server interruption and a lost provider
   response. Confirm one active checkout/subscription and preserved recovery IDs.
5. Replay/reorder signed events. Reject invalid signatures, altered bodies,
   oversized payloads and mismatched modes. Confirm receipts survive restart and
   unknown prices/multiple subscriptions project Free with review status.
6. Test invoices/payment method updates, Pro→Team upgrade with payment,
   Team→Pro period-end downgrade, and period-end cancellation in the portal.
   Confirm reconciliation reflects failed payments and cancellation dates.
7. Confirm cross-origin mutations and foreign redirects fail. Confirm desktop,
   narrow-screen, keyboard, loading, unavailable-backend and error presentation.

Source, dependency compatibility, migrations, billing security, Stripe behavior
and UI remain **UNVERIFIED** until the owner reports results. Live activation and
publication were not part of this implementation request.

References: [Stripe Checkout](https://docs.stripe.com/api/checkout/sessions/create),
[signed webhooks](https://docs.stripe.com/webhooks),
[idempotent requests](https://docs.stripe.com/api/idempotent_requests), and
[portal configuration](https://docs.stripe.com/api/customer_portal/configurations/create).
