# ACTIVE ARCS — PGT ENGINE

**Living doc. Read at STEP 0; update at close.** Guards the sequence and the live
dependencies between bricks. Standing freezes live in `canon/SESSION_CONSTITUTION.md`.

---

## The arc: PGT Engine v1 — "the works"

One engine where an AI assistant is the front (conversational intake) and an organized
admin is the back (structured, tenant-scoped data). Clonable multi-tenant from the
foundation; **PGT is tenant zero**; it runs on PGT's own site first, proven, before
it is sold.

**Verdicts (founder GO 2026-09-27):** EXPAND `pgt-site-assistant` (clean FastAPI base);
store = **Neon Postgres, new database, same account** ($0 new recurring cost);
brick-one red-control proven on a **Neon test branch**.

## Brick sequence (load-bearing first)

| # | Brick | Depends on | Status |
|---|---|---|---|
| 1 | Tenant-scoped store + RLS wall (PGT tenant zero) | — | **LANDED 2026-09-27** (wall proven: 7 passed + red control + mutation-red) |
| 2 | Lead capture → store (assistant writes leads through `with_tenant`) | 1 | **LANDED 2026-09-28** (15 passed; /chat + /contact wired; commit-rollback bug found+fixed; ⚠ found Neon `neondb_owner` BYPASSRLS → ported Tinker's **F6 defense-in-depth**, proven on real Neon; Neon provisioned + tenant zero seeded) |
| 3 | Admin auth (scrypt password + HMAC signed HttpOnly cookie) | 1 | SLATED |
| 4 | Admin view (see/organize leads, tenant-scoped) | 1,2,3 | SLATED |
| 5 | Availability store (admin edits schedule/availability) | 1 | SLATED |
| 6 | Assistant reads availability deterministically + books | 5 | SLATED |
| 7 | Human-fork at the honest edges | 2,6 | SLATED |

**One brick per cleared session. Prove it, record it, stop.**

## Owed from the founder (by brick)

- **B1:** DONE (wall proven on local PG).
- **B2:** DONE (code + proof + Neon provisioned). Decisions settled: Resend email KEPT
  as a notification alongside the store write; tenant hardcoded to `'pgt'` at the seam.
  Neon project `pgt-engine` created, pooled `DATABASE_URL` in local `.env`, `init_db`
  run (schema + RLS + PGT tenant zero seeded). ⚠ Found `neondb_owner` has BYPASSRLS →
  ported **F6 defense-in-depth** (explicit `tenant_id` filters + RLS), proven on real
  Neon. **Still owed (founder):** set the same `DATABASE_URL` in the **Render**
  dashboard so the live site persists leads.
- **F6 binds B4:** the admin view's reads MUST filter `WHERE tenant_id = ...` in SQL —
  RLS is bypassed by Neon's role, so a read that trusts RLS alone leaks.
- **B3:** `ADMIN_SESSION_SECRET`; how PGT's first admin password is set.
- **B4:** admin UI location (recommend `/admin`).
- **B5:** PGT's real availability model (enters as data via admin, not code).
- **B7:** `RESEND_API_KEY` + verified sender domain (already owed).
