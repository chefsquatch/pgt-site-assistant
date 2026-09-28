# PGT ENGINE — ARC STATE LEDGER

**The handoff.** Read at STEP 0 alongside `docs/ACTIVE_ARCS.md`. Filled from the
in-flight log at close, not reconstructed from memory. LANDED vs SLATED is
load-bearing (F5).

---

## BRICK 3 — Admin auth (scrypt password + HMAC signed HttpOnly cookie) — **LANDED 2026-09-28**

**Session:** 2026-09-28 · Opus 4.8 · founder "keep going" after Brick 2 (second brick in
one session — context barely used, so the one-brick rhythm's purpose held).

### What was built (code COMPLETE + wired)

- `app/auth.py` — faithful Python-stdlib port of Tinker's `password.ts` + `session.ts`
  (NO new dependency):
  - `hash_password` / `verify_password` — scrypt (`hashlib.scrypt`, N=16384/r=8/p=1),
    self-describing `scrypt$N$r$p$salt$hash`, per-hash random salt, constant-time compare
    (`hmac.compare_digest`); returns False (never raises) on a malformed stored value.
  - `create_session_token` / `verify_session_token` — HMAC-SHA256 signed token
    `payload.signature`, payload = base64url(JSON {tenant_id, admin_id, exp}); signature
    checked in constant time BEFORE the payload is trusted; `exp` bounds lifetime.
  - `resolve_session_secret` — dev default locally; on Render (prod) a missing
    `ADMIN_SESSION_SECRET` RAISES (fail-closed, never signs with the public dev default).
    Cookie `pgt_admin`, 12h TTL.
- `app/db_schema.py` — new tenant-scoped `admin` table (id, tenant_id, email,
  password_hash, created_at; unique(tenant_id, email)); added `"admin"` to
  `TENANT_SCOPED_TABLES` so it inherits ENABLE+FORCE RLS from `rls_policy_statements()`.
- `app/admins.py` — `find_admin_by_email` / `find_admin_by_id` / `upsert_admin`, all
  through `with_tenant` AND filtering `tenant_id` in SQL (F6 defense-in-depth). Email
  stored + matched NORMALIZED (trim + lowercase).
- `app/main.py` — `POST /admin/login` (verify → set signed HttpOnly cookie),
  `POST /admin/logout` (clear cookie), `GET /admin/me` behind a `require_admin`
  dependency. Auth is FAIL-CLOSED (not best-effort like lead capture): store/secret
  unavailable → 503, bad/expired/wrong-tenant cookie → 401. The **session-layer wall**
  (`session.tenant_id == resolved tenant id`) lives in `require_admin` (port of Tinker's
  session-guard). Login runs a constant dummy hash when the email is unknown → no
  user-enumeration timing signal. Cookie `Secure` only on Render.
- `scripts/seed_admin.py` — idempotent; seeds/resets PGT's admin from `ADMIN_EMAIL` +
  `ADMIN_INITIAL_PASSWORD` env (scrypt-hashed before it touches the DB). Separate from
  the request path, like `init_db`.
- `.env.example` — documented `ADMIN_SESSION_SECRET` + the seed vars.

### Proof — transcribed (local throwaway PG 16.4; role-switch → RLS enforced as on Neon)

- **35 passed** (11 auth-primitive + 5 admin-wall + 5 admin-endpoint + Brick 1/2's 14).
- **Watched go red — the password gate (Mutation A):** `verify_password` forced to
  `return True` → wrong-password / malformed / tampered auth tests AND the endpoint
  wrong-password 401 test FAILED. Restored → green.
- **Watched go red — the admin F6 filter (Mutation B):** dropped the `tenant_id` filter
  in `find_admin_by_email` → with RLS off, `find_admin_by_email(A, "mgr@b.test")`
  returned **B's admin** (the leak). Restored → green.
- **Admin table red control (F1):** `test_admin_wall` seeds admins in A and B, shows an
  unscoped read sees 0 with RLS on, then DISABLES RLS → raw read leaks both, while the
  filtered `find_admin_by_email` STILL isolates. (New scoped table ships with its proof.)
- **Served behavior, not just mechanism:** TestClient flow — login sets the cookie,
  `/admin/me` returns `{email, tenant:'pgt'}`, logout clears it → `/admin/me` 401 again;
  wrong password + unknown email → 401; email match is case-insensitive.
- **`seed_admin` end-to-end:** ran the script as the founder would → admin seeded; the
  stored hash verifies the correct password and rejects a wrong one.

### ⚠ Made load-bearing

- **`admin` is now in `TENANT_SCOPED_TABLES`** — it gets the wall automatically; any
  future scoped table must be added there AND ship a red-control proof (F1).
- **The request-path/auth connection is `autocommit=True`** (same contract as the lead
  seam) — `_open_store()` in main.py. A store seam that connects `autocommit=False` and
  queries before `with_tenant` hits the savepoint/rollback trap (Brick 2 note).
- **`ADMIN_SESSION_SECRET` fail-closed in prod** — admin login on Render is inert until
  the secret is set. Rotating it logs admins out but never touches stored passwords.
- **The session-layer wall lives in `require_admin`** — every future admin route depends
  on it; a cookie minted for another tenant is inert here.

### What I did NOT do (named)

- Did not build the admin VIEW/UI (Brick 4) — only the auth mechanism + endpoints.
- Did not seed the REAL PGT admin (founder's email + password to choose — owed).
- Did not run the app server (endpoints proven via TestClient).

### DEPLOYED + PROVEN LIVE (2026-09-28) — all B3 owed items DONE

- **`ADMIN_SESSION_SECRET`** — generated + set in the Render dashboard; redeployed.
- **Neon migration** — `scripts.init_db` re-run on prod → `admin` table + RLS policy
  created (additive; tenant/lead untouched).
- **Real admin seeded** — `scripts.seed_admin` run against Neon: PGT admin
  `lesfleming@precisionguessworktech.com` (1 row); stored hash verifies the password and
  rejects a wrong one.
- **Live end-to-end proof** on `https://pgt-site-assistant.onrender.com`: `/admin/login`
  → 200 + `pgt_admin` cookie; `/admin/me` → 200 `{email, tenant:'pgt'}`; wrong password →
  401; `/admin/logout` → 200 → `/admin/me` → 401. The full prod auth path (secret +
  seeded admin + walled table) works.
- Founder may reset the password anytime by re-running `scripts.seed_admin` (idempotent
  upsert). Rotating `ADMIN_SESSION_SECRET` logs the session out but keeps the password.

---

## BRICK 2 — Lead capture into the store (assistant writes leads through the wall) — **LANDED 2026-09-28**

**Session:** 2026-09-28 · Opus 4.8 · founder GO on Brick 2 + both decisions
(Resend email kept as a notification alongside the store write; tenant hardcoded to
PGT via `resolve_tenant(conn, 'pgt')` at the seam).

### What was built (code COMPLETE + wired)

- `app/leads.py` — the persistence seam:
  - `create_lead(conn, tenant_id, *, problem_summary, name, email, source)` — the pure
    write, THROUGH `with_tenant()` (F1). The row's `tenant_id` is the same id bound to
    `app.tenant_id`, so WITH CHECK admits it; a row for any other tenant is rejected.
  - `capture_lead(*, problem_summary, name, email, source, tenant_slug='pgt')` — the
    best-effort front-door helper the request paths call. Opens its own connection,
    resolves PGT (tenant zero), writes, closes. **NEVER raises** — a store hiccup can't
    regress the running assistant (F4); on failure it logs and returns `None`.
- `app/main.py` — WIRED both lead sources into the store:
  - `/chat`: when `result.handoff_ready and result.problem_summary`, persists a lead
    (`source='assistant'`, name/email null — the chat handoff carries only the summary).
    Response shape unchanged (widget contract stable).
  - `/contact`: persists the lead first (`source='contact'`, name+email+message), THEN
    sends the Resend email as before. Store = system of record; email = the founder's
    notification and the safety net so no lead is lost during the transition off the
    email-only stopgap.
- `app/db_schema.py` — added `PGT_TENANT_SLUG` / `PGT_TENANT_NAME` as the single source
  of truth for tenant-zero identity; `scripts/init_db.py` now imports them (killed the
  duplicated `'pgt'` literal so the seed and the runtime seam can never drift).
- `tests/conftest.py` — extracted the shared A/B harness here (was inline in the wall
  test): `tenants` fixture (A + B, no leads) + `h` fixture (adds one seeded lead each).
  Skips cleanly when `TEST_DATABASE_URL` is unset. `tests/test_tenant_wall.py` trimmed
  to just its tests, now using the shared fixture (no behavior change — re-proven green).
- `tests/test_lead_capture.py` — new: persistence + tenant isolation for captured leads,
  the red control, and the front-door regression test (see the bug below).

### ⚠ BUG FOUND + FIXED THIS SESSION (would have silently dropped every lead in prod)

`db.connect()` returns a connection with `autocommit=False`. In `capture_lead` the
`resolve_tenant()` SELECT opened an implicit transaction FIRST; then `with_tenant()`'s
`conn.transaction()` degraded to a nested SAVEPOINT (not a top-level txn), and the
`finally: conn.close()` **rolled the insert back**. The lead looked written
(`INSERT ... RETURNING` handed back an id) but never persisted. The pytest suite missed
it because the fixture drives `autocommit=True` (the proven config) — the unit tests
exercised `create_lead` on that connection, never the request-path flow.

**Fix:** `capture_lead` sets `conn.autocommit = True`, so each `with_tenant()` is its own
committed top-level transaction — the exact configuration the wall was proven under and
the way `init_db` commits. Documented at the seam as its contract with the Brick 1
doorway.

### Proof — transcribed from this session (read from the tool, not asserted)

Local throwaway PostgreSQL 16.4 (reused Brick 1's portable binaries; fresh cluster on
port 5433, `pgt_engine_test`, torn down after — Neon NOT touched; Tinker's branch OFF
LIMITS). Superuser connection → the fixture's NOSUPERUSER role-switch path is exercised,
so the wall binds exactly as on Neon.

- **Green at shipping state:** `pytest tests/` → **13 passed** (6 lead-capture + 7 wall).
  The conftest extraction did NOT regress Brick 1 — all 7 wall tests still pass.
- **Watched go red — the write path (Mutation A):** `create_lead._insert` neutered to
  insert nothing and return a bogus id → the 3 tests that assert a lead LANDED failed;
  the 2 that assert emptiness stayed green (proving those two alone can't guard a write).
  Restored → green.
- **Watched go red — the wall (Mutation B):** `rls_policy_statements()` → `return []` →
  the 3 isolation tests for captured leads failed (A saw B's lead: `assert 2 == 1`;
  unscoped saw rows). Restored → green.
- **Watched go red — the commit bug (regression test):** with the `autocommit = True`
  fix removed, `test_capture_lead_persists_across_a_fresh_connection` failed — the other
  connection saw `[]` while `capture_lead` had returned an id (the exact rollback bug).
  Restored the fix → green.
- **End-to-end front-door smoke:** with `DATABASE_URL` set + PGT seeded via `init_db`,
  `capture_lead(source='assistant')` and `capture_lead(source='contact')` → **2 rows
  present in PGT's `with_tenant` scope** (`('assistant', None, None)` and
  `('contact', 'Sam', 'sam@example.com')`). With `DATABASE_URL` unset → returns `None`,
  no raise (best-effort proven).
- **`init_db` still seeds tenant zero** after the shared-constant refactor:
  `{'slug': 'pgt', 'name': 'Precision Guesswork Technologies'}` created + read back.

### ⚠ Made load-bearing (a future brick breaks these silently by changing them)

- **The request-path connection MUST be driven `autocommit=True`** (each `with_tenant`
  = one committed transaction). Recorded at the site in `app/leads.py`. Any new store
  seam that connects `autocommit=False` and runs a query before `with_tenant` will hit
  the savepoint/rollback trap.
- **Tenant-zero identity lives in `app/db_schema.py`** (`PGT_TENANT_SLUG`/`_NAME`) — the
  seed and the capture seam both read it. Changing the slug in one place only reintroduces
  drift.
- **`lead.source`** distinguishes `'assistant'` (chat handoff) from `'contact'` (form).
  Brick 4's admin view will read on this; keep the values stable.
- The tenant is **hardcoded to `'pgt'`** at the capture seam (single-tenant deploy).
  Real per-slug resolution is a later brick and replaces the `tenant_slug` default only.

### What I did NOT do (named)

- Did not build bricks 3–7 (admin auth, admin view, availability, booking, human-fork).
- Did not add per-slug tenant resolution — hardcoded `'pgt'` as agreed.
- Did not run the app server (`main.py` startup requires `RESEND_API_KEY`; the store
  seam is proven directly + end-to-end without booting the web front).
- Did not deploy: Neon `DATABASE_URL` + one `python -m scripts.init_db` in prod remain
  founder-hands owed (below). The brick is proven; prod wiring is the deploy step.

### ⚠⚠ WALL DEFECT FOUND ON REAL NEON + FIXED (F6 defense-in-depth) — same session

During the Neon deploy verification (see below) I proved the RLS wall **does not hold on
the real deploy substrate**. Neon's default role **`neondb_owner` has `BYPASSRLS = true`**
(verified live 2026-09-28) — and a role with BYPASSRLS skips row-level security ENTIRELY,
even with `FORCE`. Empirically on Neon an UNSCOPED read returned rows that RLS should have
hidden. So Brick 1's claim "the wall is proven / FORCE binds Neon as-is" was **false on
Neon** — it was only ever proven on local PG via the fixture's NOSUPERUSER role switch.

**This is the exact bug Tinker hit on 2026-09-25** (`tests/tenant-defense-in-depth.test.ts`).
Tinker's adopted fix — ported here per "port known architecture, don't invent":
**defense in depth (new freeze F6).** RLS stays (defense one, for any enforcing role);
additionally **every scoped query carries an explicit `tenant_id` filter/tag in SQL**
(defense two), so isolation holds whether or not RLS runs.

- `create_lead()` already tags `tenant_id` explicitly → the WRITE path never leaked
  (the "leak" seen was a raw unscoped SELECT in a smoke script, not an engine query).
- Corrected the false comments in `db_schema.py` + `db.py`; refined `create_lead`'s.
- Added **F6** to `canon/SESSION_CONSTITUTION.md` (binds Brick 4+ admin reads to filter
  `tenant_id`, not trust RLS).
- Added `tests/test_defense_in_depth.py` — mirrors Tinker's: DISABLES RLS (the real prod
  condition) and proves the explicit `tenant_id` filter still isolates create_lead's rows.

**Proof of F6 (transcribed):**
- Full suite **15 passed** on local PG (2 defense-in-depth + 6 capture + 7 wall).
- **Watched go red:** dropped the `WHERE tenant_id` filter → with RLS off the read
  returned BOTH tenants' rows (the leak). Restored → green.
- **Proven on REAL Neon** (`neondb_owner`, RLS genuinely bypassed): an unfiltered read
  saw **2 rows** (confirming RLS is not the wall there), while reads filtered by
  `tenant_id` returned each tenant's own row ONLY. Smoke rows + throwaway tenant deleted
  → prod pristine (0 leads, only `pgt`).

### DEPLOY — Neon PROVISIONED this session (was owed)

- Neon project **`pgt-engine`** created (founder, same account as Tinker; Tinker's
  project untouched). **Pooled** connection string appended to local `.env` as
  `DATABASE_URL` (gitignored). `python -m scripts.init_db` run against it →
  schema + RLS applied, **PGT tenant zero seeded** (`slug='pgt'`).
- **Still owed (founder):** set the SAME `DATABASE_URL` in the **Render** dashboard
  (Environment tab) so the deployed site persists leads. Until then, prod chat handoffs
  no-op safely (log + return None) and the contact email still delivers — no lead lost.

---

## BRICK 1 — Tenant-scoped store + RLS wall (PGT tenant zero) — **LANDED 2026-09-27**

> ⚠ **CORRECTION 2026-09-28:** Brick 1's wall was proven only on local PG (NOSUPERUSER
> role switch). On real Neon the connecting role `neondb_owner` has **BYPASSRLS**, so RLS
> alone does NOT isolate tenants in production. Isolation now rests on **F6 defense in
> depth** (explicit `tenant_id` filters) with RLS as the second layer. See the Brick 2
> entry above. The RLS mechanism, `with_tenant()` doorway, and tenant-zero seed all stand;
> only the "RLS alone is the wall" framing was wrong.

**Session:** 2026-09-27 · Opus 4.8 · founder GO on the 7-brick sequence + EXPAND +
Neon store (new database, same account) + Neon test branch for the red control.

**Proof substrate note:** the founder had no Neon test branch and no comfort creating
one (the only Neon branch is Tinker's — deliberately NOT touched). The wall proof is
substrate-independent (standard Postgres SQL + the fixture's non-superuser role switch
makes a local cluster behave exactly as Neon), so it was proven on a **throwaway
portable PostgreSQL 16.4** (downloaded to the scratchpad, run on port 5433 as
superuser → exercised the role-switch path, then torn down). Neon remains owed for
DEPLOY only (Brick 2+), not for this proof.

### What was built (code COMPLETE)

- `app/db_schema.py` — `tenant` directory table (not scoped) + `lead` (first
  tenant-scoped table); `TENANT_SCOPED_TABLES`; `rls_policy_statements()` = faithful
  Python port of Tinker's `rls-policies.ts` (`ENABLE` + `FORCE ROW LEVEL SECURITY` +
  isolation policy `tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid`
  on both `USING` and `WITH CHECK`).
- `app/db.py` — `connect()`, `with_tenant()` (Python port of Tinker's `withTenant`;
  `set_config(..., true)` LOCAL to the txn, tenant id bound as a parameter),
  `resolve_tenant()` (port of `resolve.ts`, runs outside the wall).
- `scripts/init_db.py` — idempotent: applies schema + RLS, seeds **PGT as tenant zero**
  (`slug='pgt'`).
- `tests/test_tenant_wall.py` — the Python mirror of Tinker's `tenant-scoping.test.ts`:
  wall-holds (own rows only / not by exact id / zero rows unscoped / WITH CHECK blocks
  cross-tenant insert) + **red control** (RLS disabled → B leaks into A → restore).
- `requirements.txt` += `psycopg[binary]==3.3.6`; `requirements-dev.txt` (pytest);
  `.env.example` += `DATABASE_URL` / `TEST_DATABASE_URL` / (owed) `ADMIN_SESSION_SECRET`.
- Arc scaffolding: `canon/SESSION_CONSTITUTION.md`, `docs/ACTIVE_ARCS.md`, this ledger,
  `CLAUDE.md`.

### Proof — transcribed from this session (read from the tool, not asserted)

- **Imports + SQL shape:** `app.db`, `app.db_schema`, `scripts.init_db` import clean on
  Python 3.14; the emitted RLS SQL is byte-for-byte Tinker's wall (verified by print).
- **Green at shipping state:** `pytest tests/test_tenant_wall.py` → **7 passed** against
  local PG 16.4 (`postgresql://postgres@127.0.0.1:5433/pgt_engine_test`).
- **Red control (in-test):** `test_red_control_with_rls_disabled_B_leaks_into_A` passes
  → with RLS disabled the same scoped query returns **2 rows** (B leaks into A); restored.
- **Mutation red (watched go red):** with `rls_policy_statements()` neutered to `return []`,
  the 4 wall-holds tests FAILED as they must — A saw both rows, read B's row by exact id,
  an unscoped connection saw rows, and the cross-tenant INSERT was **not** rejected
  (`DID NOT RAISE`). Restored → **7 passed** again. The isolation is produced by the
  wall, not by accident.
- **`init_db` smoke:** applied schema + RLS and seeded **PGT tenant zero** — real row
  `{'slug': 'pgt', 'name': 'Precision Guesswork Technologies'}` created and read back.

### ⚠ Made load-bearing (a future brick breaks these silently by changing them)

- `app.tenant_id` GUC name + the `nullif(...,'')::uuid` predicate — the whole wall.
  Recorded at the site in `db_schema.py`.
- `with_tenant()` is the **only** sanctioned doorway to scoped tables. Any scoped query
  written outside it either sees zero rows (safe) or, if run unscoped by mistake, is a
  bug — never a leak, but never correct either.
- Adding a scoped table = add its name to `TENANT_SCOPED_TABLES` **and** ship a
  red-control proof for it. Forgetting the list = a table with no wall.

### What I did NOT do (named)

- Did not wire `db.py` into `main.py`/the chat or contact paths — that is Brick 2.
- Did not build bricks 2–7.
- Did not run the app (`main.py` startup requires `RESEND_API_KEY`; the store seam is
  isolated so brick 1 needs no boot).
- Did not commit — staging by explicit path awaits the green proof.

### Owed (owner: founder) — for DEPLOY, not for this proof

- **`DATABASE_URL`** — Neon (new database, same account) for `init_db` in prod + Brick 2+.
  Must be a POOLED/transaction-capable connection string (not the Neon HTTP driver).
  Guided setup deferred to when Brick 2 needs the live store; the wall itself is proven.
- **`TEST_DATABASE_URL`** — optional; only needed to re-run the wall test in CI/prod.
  Any Postgres works (proven locally this session).
