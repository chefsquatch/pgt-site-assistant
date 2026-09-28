# FRESH-SESSION HANDOFF — PGT ENGINE · BRICK 2

**Paste the block below as the opening prompt of a fresh session.** It is a cold
handoff: it assumes the next session knows nothing except what it reads. Brick 1 is
LANDED and pushed; this starts Brick 2 with the STEP-0 gate and stops for GO.

---

```
STEP-0 · PGT ENGINE · BRICK 2 — LEAD CAPTURE INTO THE STORE · READ-FIRST, STOP FOR GO

Fresh session on the PGT Engine (the clonable multi-tenant lead-and-scheduling engine;
PGT is tenant zero; built by EXPANDING pgt-site-assistant, NOT a new stack). Do not
build yet. Read the governing docs, run the STEP-0 proof-of-read, and STOP for GO.

TREE: C:\Users\chefl\Desktop\pgt-site-assistant  (PUBLIC chefsquatch/pgt-site-assistant)

READ FIRST, IN THIS ORDER (do not skip; measure against code, not memory):
  1. canon/SESSION_CONSTITUTION.md  — the STEP-0 gate + standing freezes F1–F5.
  2. docs/ACTIVE_ARCS.md            — the 7-brick sequence + live dependencies + owed.
  3. PGT_ENGINE_ARC_STATE.md        — what Brick 1 landed and what it made load-bearing.
  4. CLAUDE.md                      — the product boundary.
Then read the code you will touch: app/db.py, app/db_schema.py, app/assistant.py,
app/contact.py, app/main.py.

WHAT BRICK 2 IS:
The assistant writes captured leads THROUGH with_tenant() into the `lead` table, so the
store becomes the system of record for leads (replacing the email-only stopgap). The
assistant already emits a structured handoff object (handoff_ready + problem_summary in
app/assistant.py) — Brick 2 persists that. PGT is the tenant (slug 'pgt', seeded by
scripts/init_db.py as tenant zero).

HONOR THE FREEZES (from the constitution):
  F1 WALL     — every write goes through with_tenant(conn, tenant_id, fn). Never write a
                scoped row outside the doorway. Do not add a scoped table without adding
                it to TENANT_SCOPED_TABLES AND shipping a red-control proof for it.
  F2 DETERMINISM — not engaged this brick (that's Bricks 5–6), but do not read/store
                availability from corpus prose.
  F4 EXPAND   — add to this service; do not fork a stack or rewrite the assistant front.
  F5 LANDED vs SLATED — prove it before marking it done.

DECISIONS TO SURFACE (recommendations, for founder GO):
  - Keep the Resend email as a NOTIFICATION alongside the store write (recommend YES:
    store = truth, email = the founder still gets pinged). Confirm.
  - How the tenant is resolved for the PGT site itself: hardcode tenant 'pgt' for now
    (single-tenant deploy), resolve_tenant(conn, 'pgt') at the seam — later bricks add
    real per-slug resolution. Confirm.

OWED FROM FOUNDER (Brick 2 needs the live store):
  - DATABASE_URL — Neon Postgres, NEW database, SAME account as Tinker (decided
    2026-09-27). Must be a POOLED/transaction-capable connection string, NOT the Neon
    HTTP driver URL. The founder is not comfortable with the Neon dashboard — guide him
    in simple steps (create database → copy pooled connection string → set on Render +
    local .env) or offer to do as much as possible.
  - Run `python -m scripts.init_db` against that DATABASE_URL once to apply schema+RLS
    and seed PGT tenant zero in prod.

PROVE IT (same discipline as Brick 1):
  - A test that a captured lead is persisted under the correct tenant and is readable
    ONLY inside that tenant's with_tenant scope. Prove the test can go red.
  - Local proof substrate: a throwaway portable Postgres works and needs no Neon (see
    PGT_ENGINE_ARC_STATE.md Brick 1 note for how it was done). Tinker's Neon branch is
    OFF LIMITS — never write engine tables into it.

BUILD BRICK 2 ONLY. Land it, prove it, record it in PGT_ENGINE_ARC_STATE.md, update
docs/ACTIVE_ARCS.md, stop for GO before Brick 3.

Report measured facts from the read, then the STEP-0 proof-of-read block, then STOP.
```

---

## Quick-reference state (as of 2026-09-27, HEAD `bc40478`, pushed)

- **Brick 1 LANDED + pushed.** Wall proven: 7 passed + red control + mutation-red.
- **Store is NOT wired into chat/contact yet** — that is exactly Brick 2's job.
- **Available to Brick 2:** `app.db.with_tenant(conn, tenant_id, fn)`,
  `app.db.resolve_tenant(conn, slug)`, `app.db.connect()`.
- **`lead` columns:** `id, tenant_id, name, email, problem_summary, source, status,
  created_at`. Add columns via a follow-up if Brick 2 needs more (keep the wall list in
  sync).
- **Run tests:** `pip install -r requirements-dev.txt` then, with a Postgres URL,
  `TEST_DATABASE_URL=... pytest tests/ -v` (tests SKIP cleanly when it is unset).
- **Local Postgres for proof (no Neon needed):** download portable binaries, `initdb`,
  `pg_ctl -o "-p 5433" start`, create a db, point `TEST_DATABASE_URL` at it, tear down
  after. The wall fixture handles a superuser connection via a NOSUPERUSER role switch,
  so a local cluster behaves exactly like Neon.
