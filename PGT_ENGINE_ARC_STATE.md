# PGT ENGINE — ARC STATE LEDGER

**The handoff.** Read at STEP 0 alongside `docs/ACTIVE_ARCS.md`. Filled from the
in-flight log at close, not reconstructed from memory. LANDED vs SLATED is
load-bearing (F5).

---

## BRICK 1 — Tenant-scoped store + RLS wall (PGT tenant zero) — **LANDED 2026-09-27**

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
