# Phase 4 — UNVERIFIED owner handoff

Source baseline: DwellCall `b02b848e3c868f43aa890f0759a298ca3b45dc22`; HVACLine read-only `1667e5fb7af64502295715b9d588cf8f00732808`.
No checks, installation, services, migrations, live provider calls or publication ran.

Owner setup: configure `apps/web/.env.local` using its example. Follow `docs/authentication.md` for Neon-backed email/password, mandatory MFA and owner-approved workspace access; map the server-only backend admin token to the existing backend `ADMIN_TOKEN`. Production backend URL requires HTTPS. Preserve the existing backend environment. Node 24 and Python 3.13 are required. GHL credentials, location, opportunity settings and activation gates remain backend-managed. The GitHub link honors `DWELLCALL_GITHUB_LINK_ENABLED=false`.

Owner commands from the repository root, in an activated Python environment:

```bash
python -m pip install -e '.[dev]'
npm ci
python -m pytest tests/workspace tests/listings tests/crm
python -m pytest --ignore=tests/database
python -m pytest tests/database/test_workspace.py tests/database/test_listing_intelligence.py tests/database/test_agent_crm.py
python -m ruff check apps/backend/src/dwellcall tests migrations
python -m ruff format --check apps/backend/src/dwellcall tests migrations
python -m mypy
npm run test:web
npm run typecheck:web
npm run lint:web
npm run format:check:web
npm run build:web
```

Database specifications require a separate disposable `DWELLCALL_TEST_DATABASE_URL`; never point it at production.
After reviewing the database target and migrations, owner-only:

```bash
python -m alembic upgrade head
python -m uvicorn dwellcall.api:app --host 127.0.0.1 --port 8000
```

In a separate terminal, owner-only:

```bash
npm run dev:web
```

Acceptance: sign in; register the demo source; create/run a demo job; inspect persisted results after refresh; filter listings and inspect history/agents; resolve a retained review and reimport to apply; suppress an identity and confirm contacts/exports stay blocked; inspect GHL preview; validate owner-configured mapping; deliberately queue and separately dispatch only authorized eligible live contacts; inspect audit/recovery; check keyboard, narrow-screen and empty/error states. Existing source licenses and contact permissions remain mandatory.

Optional one-shot worker, owner-only: `python -m dwellcall.discovery_worker --max-jobs 5`. It respects saved intervals for bundled synthetic jobs only. Scheduling it requires the owner's external scheduler. Live file sources stay manual. Live feed connectors, AI enrichment and in-browser credential/location/opportunity editing are not implemented.
