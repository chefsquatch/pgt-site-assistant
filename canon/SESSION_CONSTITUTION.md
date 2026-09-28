# SESSION CONSTITUTION — PGT ENGINE

**Governs: any agent session working this tree (`pgt-site-assistant`, the PGT Engine).**
Leslie J. Fleming · adapted from Tinker's constitution rev 2 · 2026-09-27

---

## What this is for

The engine is clonable multi-tenant architecture with **PGT as tenant zero**. Its one
irreducible invariant is the **tenant wall**: no query ever crosses tenants. This
document governs **entry** and **evidence** — it reads first, and it makes proof
happen at the moment of the measurement, not reconstructed at the end. Non-compliance
must produce a **visible hole**: a required emission with an unfilled slot.

---

# STEP 0 — THE GATE

**Emit this before reading further into a brief, before opening a file, before any
tool call that changes anything. Then STOP AND WAIT FOR GO.** Also read
`docs/ACTIVE_ARCS.md` and honor its STANDING FREEZES — a move that violates a freeze
is SURFACED, never executed.

```
════════════ STEP 0 · PROOF OF READ · STOP FOR GO ════════════
BRICK: ..........................  TREE: ........................
    (absolute path, confirmed)

1 · GOVERNING RULE, QUOTED VERBATIM (source + section)
    ▎ .............................................................

2 · STANDING FREEZES, NAMED, WITH LIVE STATUS
    F1 wall ...  F2 determinism ...  F3 cost ...  F4 expand ...  F5 landed/slated ...
    F6 defense-in-depth ...
    engaged by this brick: .........................................

3 · REPOSITORY STATE, READ LIVE
    HEAD .............  origin/main ............. (read explicitly)
    ahead/behind .....

4 · THE ONE TASK I AM AUTHORIZED TO DO, QUOTED FROM THE BRIEF
    ▎ .............................................................
    OUT of scope: ..................................................

5 · ⚠ PREMISES IN THIS BRIEF I HAVE MEASURED TO BE FALSE
    ...............................................................

6 · ⚠ DOES THE RAIL ALREADY EXIST? (Tinker / this repo)
    searched: ......  found: ......
    verdict: [ ] port/parameters on something that exists → PROCEED
             [ ] a NEW mechanism → STOP AND ASK

7 · CONTEXT   used: ......%   floor: 90%

STOPPED FOR GO.
═══════════════════════════════════════════════════════════════
```

**The founder answers. Nothing proceeds on inference from silence.**

---

# STANDING FREEZES

- **F1 — THE TENANT WALL (load-bearing).** Every tenant-scoped table carries
  `tenant_id`, is listed in `TENANT_SCOPED_TABLES`, has `ENABLE` + `FORCE ROW LEVEL
  SECURITY` with the isolation policy, and is touched **only** through `with_tenant()`.
  No query crosses tenants. A new scoped table that ships without a red-control proof
  of its isolation has not landed.
- **F2 — DETERMINISTIC HONESTY.** The assistant reads availability/operational truth
  from the **structured store**, never from corpus prose, and never invents a slot.
  The corpus stays fixed grounding only.
- **F3 — NO NEW RECURRING COST** without flagging it for the founder as a decision.
- **F4 — EXPAND, DON'T FORK.** The engine lives in this one service; the proven
  conversational front is expanded, not rewritten or split into a second stack.
- **F5 — LANDED vs SLATED is load-bearing.** Never mark work done that is not wired
  and proven. A ledger entry marked done with wiring deferred is a lie in the record.
- **F6 — DEFENSE IN DEPTH (isolation must not depend on RLS alone).** ⚠ Neon's default
  role (`neondb_owner`) has **BYPASSRLS** (verified live 2026-09-28), so RLS is skipped
  entirely in production — even with FORCE. Therefore every tenant-scoped query MUST
  ALSO carry an explicit `tenant_id` filter/tag in SQL: writes tag `tenant_id`
  explicitly; reads filter `WHERE tenant_id = ...`. RLS (F1) is defense one; the explicit
  filter is defense two; they ship together. A scoped read that trusts RLS alone has not
  landed. Proof: a test that DISABLES RLS (the real prod condition) and asserts isolation
  still holds. (Same conclusion Tinker reached 2026-09-25; ported here 2026-09-28.)

---

# IN FLIGHT — PROOF IS RECORDED WHEN IT HAPPENS

- **Every zero names its control probe, run THIS session.** For the wall, that is the
  **red control**: disable RLS, watch the leak appear, restore, re-run green. A test
  nobody has watched go red is a claim.
- **Route and outcome, asserted separately.**
- **Verify the framing against code before designing the fix.**
- **Report and stop on anything outside the fence.**
- **Stage by explicit path. Never `git add -A`.** (This repo carries founder reference
  docs; `add -A` sweeps them.)
- **LANDED vs SLATED is load-bearing.**

---

# CLOSE — THE LEDGER IS THE HANDOFF

Fill `PGT_ENGINE_ARC_STATE.md` from the in-flight log (not from memory):

- **What landed**, and the commit that carries it.
- **The proof, transcribed** — the red-control leak count, the red-then-green,
  the suite result read from the tool.
- **⚠ WHAT I MADE LOAD-BEARING** — recorded at the site of the thing a future brick
  will break by changing, not only in the ledger.
- **What I did NOT do** — named. Reported-and-stopped items in full.
- **Owed items, with owners** (secrets, cost decisions, founder-hands actions).
- Update `docs/ACTIVE_ARCS.md` — it is a LIVING doc.

---

*Founded constitution-first: this file is present from the engine's first brick, so
every session measures before it acts. The deeper cases behind these rules live in
Tinker's `canon/SESSION_CONSTITUTION.md` and PGT master discipline — read them when a
rule's reason is not obvious.*
