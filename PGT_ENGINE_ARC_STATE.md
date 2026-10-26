# PGT ENGINE — ARC STATE LEDGER

**The handoff.** Read at STEP 0 alongside `docs/ACTIVE_ARCS.md`. Filled from the
in-flight log at close, not reconstructed from memory. LANDED vs SLATED is
load-bearing (F5).

---

## BRICK 7 — Human-fork at the honest edges — **LANDED + DEPLOYED + PROVEN LIVE 2026-10-26**

**Session:** 2026-10-26 · Opus 5.5 · founder "go all 4" on the STEP-0 shape. There was no written B7
spec (only the ACTIVE_ARCS row); the four pieces below are the measured gaps the founder approved.

### What was built
- **1 · A PGT handoff reaches Les.** `main._pgt_fork`: the handoff is stored (as before) AND emailed
  through the B4b rail (`notify.email_lead`, PGT has no notify_email → LEAD_INBOX, `reply_to` = the
  visitor's email, the conversation in the body). Before this brick a chat handoff was only stored,
  so Les saw it only by opening /admin. With the store down the email still goes (fallback tenant
  dict with the same no-notify_email shape).
- **2 · Email before the handoff.** PGT prompt (THE HANDOFF) now asks once for the visitor's email
  before handing off; new JSON fields `visitor_email` / `visitor_name`, parsed by `_clean_email`
  (must contain `@`, no spaces; else None, never a guess). No email given → hand off anyway.
  `/chat` takes `handed_off` (one conversation forks once) and returns `forked` + `visitor_email`.
  Widget: forked with an email → "Sent to Les. He'll reply to <email>" (no button); without one → the
  existing "Send this to Les" form button as before.
- **3 · A failed turn leaves a trace.** `main._record_edge`: a ConfigError/GenerationError on `/chat`
  or `/t/<slug>/chat` stores a `source='edge'` lead under THAT tenant (why + the last message, 500
  chars). A bad request (empty message, 400) is not an edge. No email for edges (record only).
- **4 · Handled toggle.** `leads.LEAD_STATUSES = ('new','handled')`, `set_lead_status` (with_tenant +
  `WHERE id AND tenant_id`, F6; non-uuid or other tenant's id → False), `list_leads` now orders
  `(status='new') DESC, created_at DESC`. Route `POST /admin/leads/{id}/status` behind require_admin
  (400 bad status, 404 missing/other tenant). Admin page: red "needs a person" tag + Mark handled /
  Reopen button; `edge` source tag in red. Schema: idempotent `lead_status_check` CHECK (drop + add).

### Proof, transcribed (portable PG 16.4, port 54329, `engine_test`)
- **126 passed** (was 106; +20 in `tests/test_human_fork.py`).
- **Mutations watched red, then restored (7/7 RED):** M1 status UPDATE drops its tenant_id filter →
  2 failed (lib cross-tenant + route 404); M2 handoff not emailed → 3 failed; M3 `handed_off` ignored
  → forks-once FAILED; M4 failed turn records nothing → edge test FAILED; M5 junk email trusted → junk
  test FAILED; M6 waiting-first sort removed → sort test FAILED; M7 visitor email not stored → handoff
  test FAILED. Restored → 126 passed.
- **F1/F6:** no new scoped table, so no new RLS red control owed (lead's control in
  test_tenant_wall.py unchanged + passing). The cross-tenant status tests run as the superuser (RLS
  bypassed, the Neon condition), so they hold on the SQL filter alone; M1 is that proof.
- **Migration:** `scripts.init_db` run twice on `engine_dev` (B6-era) → `CHECK (status = ANY
  (ARRAY['new','handled']))`, no error. Prod safety: `git log -S status` shows no code ever wrote
  `lead.status`, so every Neon row is the default 'new' and the CHECK applies at boot. (Could not read
  Neon directly: no DATABASE_URL in the new PC's local `.env`.)
- Not proven: a REAL-model handoff (all route tests stub the model). Owed live check below.

### ⚠ LOAD-BEARING
- `lead_status_check` and `LEAD_STATUSES` must change together (schema comment points at it).
- `_pgt_fork` sends even with the store down: the fallback tenant dict must keep `notify_email: None`
  or the email would go nowhere useful.

### What I did NOT do
- No email alert for `edge` leads (record only, as proposed). An API outage stores one edge lead per
  failed turn (no dedup); the client route is rate limited, PGT's `/chat` is not.
- Client honest declines without contact info still store nothing: the client prompt already steers
  to capture the lead, and nothing was approved there.
- No push/deploy (separate founder GO). 5b calendar sync untouched.

### Deploy + live proof (2026-10-26, founder "push")
- `76c9b99` reached origin with a parallel session's corpus commit `022c81b` on top; Render deploy
  `dep-dbfpnqvavr4c73a0uk20` live 18:29:50Z. Boot: `init_db` "schema + RLS wall applied" 18:29:43 (the
  `lead_status_check` CHECK reached Neon with no error), Uvicorn up 18:29:45.
- Real-model chat on prod `/chat`, 3 turns: the bot qualified first, said it would ask for the email
  before passing it on, then on "Fork Test (Claude), test-visitor@example.com" replied "Les has your
  summary and will reply by email to test-visitor@example.com" with `forked:true`, `visitor_email` set.
- Neon read via Render job `job-dbfpp38ae00c739jda60`: lead `0dbac936-044b-4f9e-88cb-7311b5e17419`,
  name + email stored, source 'assistant', status 'new'. **Founder confirmed** the alert email arrived
  and Reply addresses the visitor. Test lead DELETED by exact id (job `job-dbfpsh0m7kps739e5pfg`,
  "deleted 1").
- Observed, not a B7 bug: after the fork the bot also offered a call-back (PGT has hours), which is the
  B6 flow working alongside. App INFO logs don't print on Render, so the email send is proven by the
  founder's inbox, not the log.

### Owed / next
- None for B7. The 7-brick arc's only remaining brick is 5b calendar sync (Google OAuth = founder setup).

---

## BRICK 6 — The assistant reads availability deterministically + books — **LANDED + DEPLOYED + PROVEN LIVE 2026-10-26**

**Session:** 2026-10-26 · Opus 5.5 · founder GO on the STEP-0 shape, plus the gating ruling
"booking only for tenants that have entered weekly hours" (agreed). Rulings carried from
ACTIVE_ARCS (settled 2026-10-26): instant block, 30-minute slots, 2-week horizon; PGT flavor =
email first, then a confirmed call-back time, and Les calls; clone flavor = plain slot booking.

### What was built
- `app/availability.py`: `Slot` (id = local `YYYY-MM-DDTHH:MM`, label `Tue Oct 27, 10:00 AM EDT`),
  pure `compute_slots()` (30-minute cells wholly inside an open window, future only), `open_slots()`
  (= `open_windows(days=14)` → slots, F2), `book_slot()` (the store decides: the id must be in
  `open_slots()` RIGHT NOW, then `add_block(source='booking')`; a unique-index loss = `SlotUnavailable`),
  `slots_for_prompt()` (one line per day, capped at the soonest 120). `BLOCK_SOURCES` += `'booking'`.
- `app/db_schema.py`: additive + idempotent: the block `source` CHECK widened to include `'booking'`
  (explicit DROP/ADD, because CREATE IF NOT EXISTS never revisits a CHECK), plus the partial unique index
  `availability_booking_slot_uq (tenant_id, starts_at) WHERE source='booking'`. **No new scoped table.**
- `app/booking.py` (NEW): best-effort seam like the lead seam. `read_slots()` returns [] on any failure;
  `try_book()` books, records the booking as a lead (`Call-back booked for …` / `Appointment booked for …`),
  emails the owner (PGT → LEAD_INBOX) and **writes the visitor's reply from what the store did**.
  Never raises.
- `app/assistant.py`: `book` proposal in both JSON shapes (`_parse_book`: slot + name + phone, and PGT also
  requires an email, the "email first" ruling). PGT gets a CALL-BACKS section and the client gets OPEN TIMES
  rules, both **only when slots exist**. With no slots, both prompts are byte-identical to the pre-brick
  prompts (checked against HEAD, and test-pinned for PGT).
- `app/main.py`: `/chat` + `/t/<slug>/chat` read slots before the model call, take `booked` (one booking per
  conversation), and return `booking: {slot,label,start}|null`. On a booking turn the model's own text is
  REPLACED by the store's answer.
- `app/notify.py`: a `BOOKED:` line and a `Booked <time>: <name>` subject for booking alerts.
- `static/widget.js`, `static/client-widget.js`: send `booked`, set it from `booking`. The confirmation
  is the reply bubble (the server wrote it).

### Proof, transcribed (portable PG 16.4, port 54329)
- **106 passed** (was 82; +24 in `tests/test_booking.py`).
- **Mutations watched red, then restored (8/8 RED):** M1 book_slot trusts the model's id → 7 failed
  (every invented-slot case + the route); M2 no unique index → 2 failed (race + index tests); M3 block
  read drops its tenant_id filter → 3 failed (RLS-off wall test + both route bookings); M4 slots aligned
  to the window start → grid test FAILED; M5 past slots offered → past test FAILED; M6 client reply =
  model text → 2 failed; M7 PGT books without email → email-first test FAILED; M8 `booked` ignored →
  books-once test FAILED. Restored → 106 passed.
- **Red control (F1/F6):** `availability_block` RLS disabled → raw read leaks B's booking (count 1 with
  no tenant context), while A's and B's slot reads still isolate on the SQL filter; restored.
- **Migration on an existing B5-era DB (`engine_dev`):** before = `CHECK (source IN ('manual','calendar'))`;
  `scripts.init_db` run twice (idempotent) → `CHECK (… 'booking')` + the partial unique index present.
  Prod applies it on the next boot via the start command (`init_db; uvicorn`).

### ⚠ Made load-bearing (also recorded at the site)
- **The fixed :00/:30 grid** (`compute_slots`): overlapping bookings ⇔ the same start, which is the
  only thing `availability_booking_slot_uq` checks. Changing the slot length or the alignment without
  revisiting the index re-opens double-booking. A window starting off-grid (9:15) loses its partial cell.
  Zones with a :45 offset would misalign (no US zone has one).
- **The model only proposes; the store decides; the server writes the confirmation.** Never let a
  model-written "booked" reach the visitor on a booking turn.
- **No weekly hours = no slots = booking off.** That is the gate the founder ruled; it needs no flag.
- **Cancel = delete the booking's block** on the Availability tab (source tag `booking`); the slot
  reopens at once.

### What I did NOT do (named)
- **No push, no deploy, no Neon touch.** The GO covered building. On deploy, the boot-time `init_db`
  applies the schema change (no manual Neon step owed).
- **No real-model conversation run.** This PC has no `ANTHROPIC_API_KEY` locally, so every route test
  stubs the model. Whether the real model follows the flow (email → phone → offer 2-3 listed times →
  `book`) is UNPROVEN until a live chat after deploy. Mechanism verified, outcome unproven.
- **Prose guard not built:** on a NON-booking turn the model could still write a time or "you're booked"
  in prose. The prompt forbids it, but no server check catches it (a regex scanner over the reply = the
  known false-positive trap). The booking itself can never be invented; the prose can.
- **No abuse cap on bookings:** the `booked` flag is client-held, and PGT `/chat` has no rate limit, so a
  script could fill a calendar. Admin deletes the blocks. Slated if it ever happens.
- **No minimum notice:** any future slot is bookable, even one 5 minutes out. A per-tenant notice setting
  would be a founder ruling.
- 5b calendar sync and 7 human-fork untouched.

### Deploy (2026-10-26, founder GO "go")
- Pushed `b1aed1c`; Render deploy `live` 14:32:07Z. Boot log: `init_db` "schema + RLS wall applied" at
  14:32:01 (the CHECK widen + booking index reached Neon), Uvicorn up 14:32:04, no errors. `/health` ok
  throughout. No booking can happen yet: PGT has no weekly hours entered, so booking is off for it.

### Live proof (2026-10-26, real model, production)
- PGT hours entered as data via a Render one-off job (`job-dbfncqmi0phs73bacvc0`, founder GO; auto mode had
  blocked remote-shell writes, and `render ssh` needs a TTY, so one-off jobs are the working rail): Mon-Fri
  10:00-16:00 America/Detroit → 116 open slots.
- Real chat on prod `/chat` (5 turns): visitor asked for a call → the assistant asked for EMAIL FIRST, then
  name + phone → listed real slots → asked which Wednesday → `booking: 2026-10-28T14:00`, reply = the
  server's "Done, you're booked: Les will call you at 810-555-0100 on Wed Oct 28, 2:00 PM EDT…".
- Verified in Neon (read-only job `job-dbfnudnavr4c73dh94ug`): one `booking` block at 18:00Z, the slot gone
  from `open_slots`, lead `Call-back booked for Wed Oct 28, 2:00 PM EDT. …`. No errors in the service log.
- TEST DATA in prod (delete after founder confirms the email): block `6e53527a-bc4b-4a5a-a8ab-b4826ec39bea`,
  lead `09b70f25-ea4e-4d60-be8c-24db8c63192c` ("Booking Test (Claude)", 555 number).
- Observed, slated for tuning (prompt-only, not bugs in the booking rail): the model listed ALL two weeks of
  slots instead of 2-3; replies still contain em dashes despite the VOICE rule (pre-existing, not B6).

### Owed / next
- **Founder-hands, after deploy:** enter PGT's real call-back hours on the Availability tab (booking turns
  on for PGT the moment hours exist), then run one real chat on the site through to a booked call-back,
  and confirm the email arrives and the block shows up. For a client, the same on `pgt-sample-plumbing`.

---

## BRICK 4b — Client tenants (a paying local business is a tenant) — **LANDED 2026-10-25 (code + tests); live proof below**

**Session:** 2026-10-25 · Opus 5.5 · founder GO (remote): "i approve any and all that you can you
handle without me at the box". Why now: founder near the financial brink, goal ~$300/mo from local
clients ($69 build + $99/mo). The demos sold things a client could not get; this makes the core
deliverable real: 24/7 grounded answers on the client's site, every lead stored under that client
and emailed to its owner, and the owner's own login to see them. **Inserted ahead of B5b/B6/B7 by
founder ruling.** Text alerts deliberately NOT built (F3: Twilio = recurring cost + founder-made
account + A2P registration); email only until a client is paying.

### What was built
- `app/db_schema.py` — additive, idempotent: `tenant.notify_email` (directory row: the owner's alert
  address, NULL for PGT) and `lead.phone`. **No new scoped table** (so no new RLS red control owed;
  `lead`'s existing control in test_tenant_wall.py still passes).
- `app/db.py` — `resolve_tenant` returns `notify_email`; NEW `get_tenant_by_id` (directory read; a
  malformed id is None).
- `app/leads.py` — `phone` through `create_lead`/`capture_lead`/`list_leads` (F6 tag/filter unchanged).
  The capture seam's per-slug resolution (built in B2 "for later bricks") is now used.
- `app/corpus.py` + `config.TENANTS_CORPUS_DIR` — profile `tenant:<slug>` → `corpus_tenants/<slug>/`.
  ⚠ LOAD-BEARING: `valid_slug` (`^[a-z0-9]+(-[a-z0-9]+)*$`) is checked before a slug becomes a path.
- `app/assistant.py` — `respond_client` + `_client_system_prompt`: rails PORTED from the proven
  vertical-demos prompt (grounded / honest-or-quiet / capture-the-lead; never "booked", never an ETA,
  no card data) in the engine's JSON convention. A lead counts only with a name AND a phone or email.
- `app/notify.py` (NEW) — `email_lead`: Resend, to the tenant's `notify_email`, cc PGT `LEAD_INBOX`,
  from `CLIENT_LEAD_FROM` (verified PGT domain). Best-effort, never raises.
- `app/main.py` — `POST /t/{slug}/chat` (404 unknown/malformed slug, per-IP rate limit ported from
  vertical-demos, one lead per conversation via `lead_captured`, urgent → `URGENT: ` prefix + subject);
  `/t/` CORS layer answering any origin (no credentials ride on it; every other route keeps the
  allow-list); `GET /client-widget.js`; admin login takes `workspace` (default `pgt`; unknown
  workspace = same 401 as a wrong password). ⚠ LOAD-BEARING CHANGE: `require_admin` now scopes to
  the tenant in the HMAC-signed session (`get_tenant_by_id`) instead of hardcoding PGT; the wall is
  "a session sees only its own tenant", and the admin must still exist inside that tenant.
- `static/client-widget.js` (NEW) — the drop-in for a client's own site, ported from the pgt-demos
  overlay chat (a020999). `static/admin.html` — `?w=<slug>` workspace + Phone column.
- `scripts/add_tenant.py` (NEW, idempotent upsert); `scripts/seed_admin.py` takes `TENANT_SLUG`.
- `corpus_tenants/pgt-sample-plumbing/` — a clearly-labeled SAMPLE business for live proof and demos.

### Proof — transcribed (portable PG 16.4, port 54329; app connects as superuser = RLS bypassed, the Neon condition)
- **82 passed** (was 68: +14 in `tests/test_client_tenants.py`). Every isolation assertion holds on
  F6 filters alone, because the app's connection bypasses RLS.
- **Mutations watched red, then restored (7/7 RED):** A seam writes to PGT not the slug → lead test
  FAILED; B login ignores workspace → owner-workspace test FAILED; C guard skips admin-in-tenant →
  hand-minted cross-tenant session test FAILED; D `lead_captured` ignored → one-lead test FAILED;
  E `/t/` CORS layer removed → origin test FAILED; F slug check removed → path test FAILED; G alert
  not sent to the owner → lead/email test FAILED. Restored → 82 passed.

### Deploy mechanism (⚠ LOAD-BEARING, 2026-10-25)
- Render's Pre-Deploy Command is locked on this service, so the **Start Command** is now
  `python -m scripts.init_db; uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Every boot re-applies
  the idempotent schema + RLS before serving, using Render's own DATABASE_URL (no secret leaves Render).
  `;` not `&&`: a Neon hiccup at boot can't take the site down (worst case a new route 500s until the
  next boot). This retires the "run init_db against Neon before deploying" owed step for every future
  brick. Proven: the first boot with it logged `[init_db] schema + RLS wall applied`.

### Live proof on production (2026-10-25, after the Starter upgrade)
- Service moved Free → **Starter ($7/mo, founder-approved)**: no spin-down, Shell available, no
  shared free-hours cap. `add_tenant` run in Render Shell → `pgt-sample-plumbing` registered.
- Served text, `POST /t/pgt-sample-plumbing/chat` from outside (Origin example-client.com, ~3s each):
  "How much is a service call?" → "$89, and we waive that fee if we end up doing the repair." (corpus);
  "Do you install solar panels?" → "We don't install solar panels..." (declined, nothing invented);
  leaking water heater + "Les Test, 810-555-0142" → lead `{urgent:true}` returned, and Neon holds
  `('Les Test','810-555-0142','URGENT: Water heater leaking in basement')` under that tenant only.
- **Alert email FAILED live:** Resend 403 "precisionguessworktech.com domain is not verified". The
  site's RESEND_API_KEY belongs to a Resend account without the domain (the verified one is on a
  different account). Fix: `CLIENT_RESEND_API_KEY` (falls back to RESEND_API_KEY), used only by
  `notify.py`, so the contact form keeps its key. Test asserts the alert rides the client key; red
  control (alert on the old key) → FAILED; restored → 82 passed. **Owed (founder hands): paste the
  verified-domain account's Resend key into CLIENT_RESEND_API_KEY on this service, then re-run the
  lead test.** Until then, client leads are stored and visible on /admin but not emailed.
- **✅ FIXED + PROVEN LIVE 2026-10-26:** tinker's `RESEND_API_KEY` (the verified-domain account)
  copied server-side via the Render API into `CLIENT_RESEND_API_KEY` on pgt-site-assistant (never
  printed; read-back matched), redeployed (`dep-dbflns1srm7s73feplvg` live). Re-ran the lead test on
  `/t/pgt-sample-plumbing/chat` ("Les Test, 810-555-0142", leaking water heater) → `{urgent:true}`,
  no alert error in the Render log, and the founder confirmed the alert emails arrived (two: to + cc).

### What I did NOT do
- SMS/text alerts (F3, founder account needed). Lead status editing. Per-tenant branding of /admin.
- Seeded no admin password for any tenant (credentials are the founder's to choose).

### Owed
- Founder, per client: write `corpus_tenants/<slug>/` from their real info, `add_tenant` with their
  alert email, `seed_admin` with `TENANT_SLUG`, paste the widget tag on their site.
- If Resend rejects `leads@precisionguessworktech.com` on this service's key, verify the domain on that
  Resend account (alerts still store the lead; only the email fails, logged).

## BRICK 5 — Availability store (admin edits the schedule; it lives as data) — **LANDED 2026-10-24**

**Session:** 2026-10-24 · Opus 5.5 · founder GO "Yes, build Brick 5". Founder framing, verbatim:
the engine "is the clonable version for what i sell to small business so it needs to do what i
advertise for others basically, wether i use it that way or not" — availability must support
BOTH manual weekly hours AND calendar sync. PGT's own use: "prefer to have the assistant fork to
email then confirm or set a time for a call back then i'd call them" (no video; phone only as a
call-back). Recorded here because it shapes Brick 6 (see below).

### What was built

- `app/availability.py` (NEW) — three scoped tables' rails, all through `with_tenant` AND
  filtering/tagging `tenant_id` in SQL (F6): `get_timezone`/`set_timezone` (IANA-validated),
  `add_window`/`list_windows`/`delete_window` (weekday 0-6, **0 = Sunday — Tinker's
  convention, ported from `src/schedule/types.ts`**, "HH:mm" local, no midnight crossing),
  `add_block`/`list_blocks`/`delete_block` (absolute instants; `source` 'manual' | 'calendar').
  `compute_open_windows` (PURE: each local day's weekly windows minus blocks, resolved per date
  via zoneinfo so DST keeps wall-clock times) + `open_windows(conn, tenant, start_date, days)` —
  **the deterministic read Brick 6 books against (F2).** Malformed ids → "not found", never a DB
  type error.
- `app/db_schema.py` — `availability_settings` (one row/tenant, PK tenant_id),
  `availability_window` (CHECK weekday 0-6, end > start), `availability_block` (CHECK ends >
  starts, source IN ('manual','calendar')); all three appended to `TENANT_SCOPED_TABLES` →
  ENABLE + FORCE RLS + isolation policy. Additive (`IF NOT EXISTS`).
- `app/main.py` — guarded (`require_admin`) routes: `GET /admin/availability`,
  `PUT /admin/availability/timezone`, `POST|DELETE /admin/availability/windows[/{id}]`,
  `POST|DELETE /admin/availability/blocks[/{id}]` (block times entered as wall time in the
  tenant's zone), `GET /admin/availability/open?days=N` (1-62). Bad input → 400 with the reason;
  store down → 503. Block times are RENDERED in the tenant's zone (the DB returns its session zone).
- `static/admin.html` — Leads | Availability tabs; time zone, weekly hours (add/remove), blocked
  time (add/remove, source tag), and a "Open in the next 14 days" preview of the exact read the
  assistant will use.
- `requirements.txt` — `tzdata==2026.5` pinned (Windows has no system tz db; it was only arriving
  transitively). No new service, **no recurring cost (F3)**.
- `tests/test_admin_endpoints.py` — teardown now drops every scoped table by list (the hand-written
  admin/lead/tenant drop broke on the new FKs). No assertion changed.

### Proof — transcribed (portable PG 16.4 at `PGT\tools\pg16`, port 54329; superuser → fixture role-switch, RLS enforced as on Neon)

- **68 passed** (was 50: +18 in `tests/test_availability.py` — 7 pure, 7 wall incl. the red control
  parametrized ×3 tables, 4 endpoint).
- **Red control per new table (F1):** RLS on → unscoped read 0; RLS DISABLED → raw read **2** (the
  leak) on each of the 3 tables; the app's reads + cross-tenant deletes still isolate (F6). Restored.
- **Mutations watched red, then restored:** (A) `list_windows` without `tenant_id` filter →
  `test_red_control…[availability_window]` FAILED; (B) `delete_block` without `tenant_id` →
  `…[availability_block]` FAILED (A could delete B's block); (C) block subtraction disabled → 4
  FAILED (split, whole-day, cross-zone instant, store read). Note A/B were caught ONLY by the
  RLS-off test — exactly F6's point. Restored → 68 passed.
- **DST:** a Monday 09:00 window stays 09:00 local across 2026-11-01 (offset -4 → -5), test-pinned.
- **Served behavior, live server:** `init_db` + `seed_admin` on a fresh DB, uvicorn on :8765,
  curl: login → empty view → add Tue 09-12 + Thu 13-15 → block Tue 10-11 → reversed window → 400
  "end must be after start" → `/open?days=7` = Tue 09-10, Tue 11-12, Thu 13-15 (-04:00) →
  `/admin` 200, unauthed `/open` 401. Admin page script passes `node --check`.

### ⚠ Made load-bearing

- **`open_windows()` is THE availability read.** Brick 6 must book against it, never against corpus
  prose (F2). A calendar-sync brick WRITES `availability_block` rows with `source='calendar'`; it is
  a writer into this store, never a second source the assistant reads.
- **Weekday 0 = Sunday** (Tinker's convention) — `compute_open_windows` converts from Python's
  Mon=0. Changing either side silently shifts every window a day.
- Every availability read/delete filters `tenant_id` in SQL (F6); keep it on any new query.

### What I did NOT do (named)

- **No Neon migration, no push, no deploy** — founder GO was "build", not deploy. Prod needs
  `python -m scripts.init_db` against Neon (additive) BEFORE the deploy that serves these routes;
  until then `/admin/availability*` would 500 on the missing tables.
- **No browser eyeball of the Availability tab** — no browser tool in this session. The API flow
  and the script's syntax are proven; the rendered layout is founder-hands (`/admin` → Availability).
- **Calendar sync not built** (founder: "both") — slated as its own brick (Google OAuth = founder
  setup; writes busy times as `source='calendar'` blocks). Brick 6/7 untouched.

### Owed / next

- **Founder-hands:** look at the Availability tab live (local or after deploy); enter PGT's real
  call-back hours.
- **Deploy (on founder GO):** Neon `init_db` → push → Render auto-deploys.
- **Brick 6 shape, from the founder's words:** for PGT the assistant forks to email, then confirms
  or sets a call-back time from `open_windows()`; the founder calls them. The clonable engine also
  needs plain slot booking for tenants that sell it. Founder rules the shape at Brick 6's STEP-0.

---

## TINKER IN-APP HELP PROFILE — **LANDED 2026-10-24** (founder GO; F3 cost flag given)

Founder chose "reuse your website assistant" for Tinker's Help button (a few cents per
conversation, on the existing Claude key). F4 honored: same service, second PROFILE, not a fork.
- `corpus_tinker/00-tinker-help.md`: Tinker how-to grounding (every screen with real labels;
  hours-not-pay; no pricing; no em dashes, test-enforced).
- `app/corpus.py`: `load_corpus(profile)` / `corpus_sections(profile)` / `is_empty(profile)`,
  default "site" so every existing caller is unchanged.
- `app/assistant.py`: model call factored into `_call_model` (shared); `respond_tinker` +
  `_tinker_system_prompt` (grounded-or-honest, `needs_human` + `issue_summary` for handoff, fail
  safe on bad JSON = not grounded + human path, empty corpus = no model call).
- `POST /tinker/help` {history} -> {reply,in_corpus,needs_human,issue_summary}. Server-to-server
  from Tinker (Tinker owns the admin session and sends the escalation email itself via its own
  Resend), so no CORS, nothing stored, no lead capture. `/health` lists `tinker_help_sections`.
- Site chat: "Never use em dashes" added to VOICE; visible fallback strings de-dashed (founder rule).
- `tests/test_tinker_help.py` 9 tests; red proven (site corpus leak, bad-JSON grounded, empty
  corpus model call). Suite 19 passed / 31 skipped (DB); smoke_contact 13/13, smoke_errors 10/10.

---

## BRICK 4 — Admin view (see captured leads, tenant-scoped) — **LANDED 2026-10-09**

**Session:** 2026-10-09 · Opus 4.8 · founder queued "after that brick 4" (after the
vertical-demos Render fix). No schema change — Brick 4 only READS the existing `lead` table.

### What was built

- `app/leads.py` → `list_leads(conn, tenant_id)` — the read-side counterpart to
  `create_lead`: through `with_tenant` (defense one) AND `WHERE tenant_id = %s` (F6,
  defense two), newest first. Returns dicts (created_at ISO-formatted).
- `app/main.py` → `GET /admin/leads` (behind `require_admin`; opens an autocommit store
  conn, calls `list_leads`, returns `{leads, count}`) + `GET /admin` (serves the admin
  page; the page is public HTML, no tenant data embedded — the guarded `/admin/leads` is
  what gates the data).
- `static/admin.html` — self-contained page in the site's dark/Oswald brand: shows the
  sign-in form until a valid session cookie exists, then calls `/admin/leads` and renders
  the leads table (name / email / problem / source tag / status / when). Uses
  `credentials:"same-origin"` so the HttpOnly cookie rides along; sign-out posts
  `/admin/logout`.

### Proof — transcribed (local throwaway PG 16.4, role-switch → RLS enforced as on Neon)

- **41 passed** (6 new: 3 `list_leads` in test_lead_capture + 3 endpoint in
  test_admin_endpoints; + Brick 1–3's 35).
- **Watched go red (F6):** dropped the `tenant_id` filter in `list_leads` → with RLS off,
  `list_leads(A)` returned `['B','A']` (both tenants) instead of `['A']` — the leak.
  Restored → green. (The RLS-ON test stayed green under the mutation, proving it's the
  defense-in-depth test that catches a missing filter — exactly the point of F6.)
- **Endpoint scoping:** `/admin/leads` → 401 unauthed; authed returns ONLY the signed-in
  tenant's 2 leads, never the seeded "OTHER tenant lead" (via TestClient).
- **Served behavior (GREEN STANDARD — not just mechanism):** booted the app locally
  against a seeded store, opened `/admin` in a browser, signed in, and saw the real leads
  table render (3 leads, source tags, session persisting across reload). **Caught + fixed
  a rendering bug in the browser:** the no-name cell showed the literal
  `<span class="muted">—</span>` because `esc()` wrapped the HTML fallback; fixed to
  `l.name ? esc(l.name) : '<span…>'` (same shape the email cell already used). Re-verified
  the "—" renders correctly.

### ⚠ Made load-bearing

- `list_leads` is the sanctioned read rail — it filters `tenant_id` in SQL (F6). Any
  future admin read of a scoped table must do the same, never trust RLS alone on Neon.
- `/admin` serves PUBLIC HTML with NO tenant data embedded; `/admin/leads` is the guarded
  data endpoint. Keep that split — don't server-render tenant rows into the page.

### What I did NOT do (named)

- No schema/Neon migration (Brick 4 reads only; `admin`+`lead` tables already on Neon).
- No lead status EDITING / organizing beyond display (could be a later brick).
- Availability/booking (B5–B6), human-fork (B7) — untouched.

### Deploy

- Code-only; pushed → Render auto-deploys. Admin login already live from Brick 3
  (secret + seeded admin), so `/admin` is usable in prod immediately after deploy.

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
