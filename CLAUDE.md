# CLAUDE.md — Operational Canon (PGT Engine)

Git-tracked operational canon for the **PGT Engine** — a clonable, multi-tenant
lead-and-scheduling engine where an AI assistant is the front (conversational intake)
and an organized admin is the back (structured, tenant-scoped data). **PGT is tenant
zero**; the engine runs on PGT's own site (`precisionguessworktech.com`) first, proven,
before it is sold. It is built by EXPANDING this service (`pgt-site-assistant`), not by
forking a new stack.

**Read at the start of every session, before proposing any move.**

## STEP 0 — the gate (every session)

Before proposing any move — before opening a file or any tool call that changes
anything — read `canon/SESSION_CONSTITUTION.md`, emit its STEP-0 proof-of-read block,
and STOP AND WAIT FOR GO. Also read `docs/ACTIVE_ARCS.md` and honor its STANDING
FREEZES. `PGT_ENGINE_ARC_STATE.md` is the live handoff ledger.

## The product boundary (load-bearing)

- **The tenant wall is the single most important invariant.** No query crosses
  tenants. Tenant-scoped tables carry `tenant_id`, live in `TENANT_SCOPED_TABLES`,
  have `ENABLE` + `FORCE ROW LEVEL SECURITY`, and are touched only through
  `with_tenant()`. (F1)
- **Deterministic honesty.** The assistant reads availability/operational truth from
  the structured store, never from corpus prose, and never invents a slot. The corpus
  stays fixed grounding. (F2)
- **No new recurring cost without a founder flag.** (F3)
- **Expand, don't fork** — one service, the proven conversational front is not
  rewritten. (F4)

## Build + verify rhythm

- One brick per cleared session. Prove it, record it, stop.
- One change = one commit = green tests. **Stage by explicit path; never `add -A`**
  (this repo carries founder reference docs at root).
- **Prove the test can go red** before trusting it green — for the wall, the red
  control is disabling RLS and watching B leak into A.
- **LANDED vs SLATED is load-bearing** — never mark work done that is not wired and
  proven.

## The store

Neon Postgres (new database, same account as Tinker), psycopg3 for real transactions.
Schema + RLS applied by `python -m scripts.init_db` (never by the request path). The
RLS wall is a faithful port of Tinker's proven pattern (`chefsquatch/tinker`,
`src/db/rls-policies.ts` + `rls.ts`).

---

*Founded constitution-first: `canon/SESSION_CONSTITUTION.md` is present from Brick 1,
so every session measures before it acts.*
