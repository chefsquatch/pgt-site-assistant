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
| 3 | Admin auth (scrypt password + HMAC signed HttpOnly cookie) | 1 | **LANDED 2026-09-28** (35 passed; scrypt+HMAC ported from Tinker, stdlib-only; `admin` scoped table + red control + F6; login/logout/me proven via TestClient; owed: `ADMIN_SESSION_SECRET`, seed real admin, Neon migrate) |
| 4 | Admin view (see/organize leads, tenant-scoped) | 1,2,3 | **LANDED 2026-10-09** (41 passed; `list_leads` F6-filtered + `/admin/leads` guarded + `/admin` page; proven in-browser login→leads; no schema change) |
| 4b | Client tenants: a business is a tenant (own knowledge, own leads, owner alert email, owner login, embeddable widget) | 1,2,3,4 | **LANDED 2026-10-25** (82 passed; 7 mutations red; founder-inserted ahead of 5b/6/7; email alerts only, SMS deferred under F3) |
| 5 | Availability store (admin edits schedule/availability) | 1 | **LANDED 2026-10-24** (68 passed; 3 walled tables + red control ×3 + F6 mutations red; deterministic `open_windows()` DST-safe; admin Availability tab; ⚠ NOT deployed: Neon `init_db` owed before the deploy) |
| 5b | Calendar sync (business's busy times → `availability_block` source='calendar') | 5 | SLATED (founder: engine must do "both"; Google OAuth = founder setup) |
| 6 | Assistant reads availability deterministically + books | 5 | **LANDED 2026-10-26** (106 passed; 8 mutations red; 30-min fixed-grid slots, instant `source='booking'` block, unique index vs double-booking; model proposes, store decides, server writes the reply; booking only when hours exist; DEPLOYED + PROVEN LIVE 2026-10-26 on a real-model chat) |
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
- **B3:** DONE + DEPLOYED + PROVEN LIVE. `ADMIN_SESSION_SECRET` set in Render; Neon
  migrated (`admin` table); PGT admin `lesfleming@precisionguessworktech.com` seeded.
  Live login/me/logout verified on the deployed site. Founder resets the password via
  `scripts.seed_admin` (idempotent). Cookie `pgt_admin`, 12h TTL.
- **B4:** DONE. Admin UI at `/admin` (served page) + `GET /admin/leads` (guarded, F6).
  No new owed — admin login was wired in B3 (secret + seeded admin), so `/admin` is live
  in prod on deploy. Future: lead status editing / organizing (not in v1 scope).
- **B5:** LANDED (code). Owed: run `python -m scripts.init_db` against Neon BEFORE deploying (the
  routes 500 without the 3 new tables); eyeball the Availability tab; enter PGT's real call-back
  hours as data. PGT's model (founder 2026-10-24): email first, then a confirmed call-back time —
  no video, phone only as a call-back.
- **B4b:** per client: `corpus_tenants/<slug>/` + `scripts.add_tenant` + `scripts.seed_admin` (TENANT_SLUG) + widget tag on their site. SMS alerts = founder decision (Twilio account, cost) once a client pays.
- **B6 (founder rulings 2026-10-26, settled — don't re-ask):** a booking blocks the slot
  INSTANTLY (no approval step; writes an `availability_block`); slots are **30 minutes**;
  booking horizon is **2 weeks** (= `open_windows(days=14)`). PGT's flavor: email captured
  first, then offer real call-back times, confirm, founder calls. Clone flavor: plain slot booking.
  Plus (STEP-0 2026-10-26): booking is on only for tenants with weekly hours. **LANDED + DEPLOYED.** PGT hours
  (Mon-Fri 10-16) entered; real-model booking PROVEN LIVE (founder confirmed the booking email; test block + lead deleted by exact id, slot open again). Tuning: offer 2-3 slots, not the full list. Open: no minimum notice, no booking abuse cap, no
  server check on time/"booked" prose outside booking turns.
- **B7:** `RESEND_API_KEY` + verified sender domain (already owed).
- **B4b client alerts:** DONE 2026-10-26 — `CLIENT_RESEND_API_KEY` set on Render (verified-domain
  key from tinker), live lead test emailed (founder confirmed receipt).
