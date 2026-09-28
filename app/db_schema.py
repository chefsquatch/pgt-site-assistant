"""The engine's schema and the RLS wall — Brick 1 (the load-bearing wall).

Ported faithfully from Tinker's proven pattern (src/db/schema.ts + rls-policies.ts).
The wall is DB-level, so the port is exact even though Tinker is TypeScript/Drizzle
and this is Python: the SQL that raises the wall is identical.

Two kinds of table:
  * `tenant` — the DIRECTORY of tenants. It is NOT tenant-scoped (it is the index of
    tenants themselves); it gets no wall and is read OUTSIDE with_tenant().
  * every table in TENANT_SCOPED_TABLES — carries `tenant_id` and is walled by RLS so
    one tenant can never read, mutate, or write into another tenant's rows.

Brick 1 ships exactly one scoped table, `lead`, so the wall can be PROVEN on real
data. Brick 2 writes captured leads into it; later bricks add more scoped tables and
only need to append their name to TENANT_SCOPED_TABLES to inherit the same wall.
"""

from __future__ import annotations

# --- The setting the wall reads. Kept identical to Tinker's ("app.tenant_id") so the
# mechanism is recognisably the same across the two repos.
TENANT_SETTING = "app.tenant_id"

# --- Tenant zero — PGT itself. The engine runs on PGT's own site first, so PGT is the
# first tenant, seeded by scripts/init_db.py. It is the single source of truth for the
# slug both the seed (init_db) and the runtime lead-capture seam (app/leads.py) use, so
# the two can never drift. Later bricks replace the hardcoded resolution with real
# per-slug resolution; this constant is where "which tenant is PGT" lives until then.
PGT_TENANT_SLUG = "pgt"
PGT_TENANT_NAME = "Precision Guesswork Technologies"

# --- Tables that carry tenant_id and MUST be walled. A scoped table that is not listed
# here gets no wall — so adding a scoped table without adding it here is the one silent
# gap, and the wall test seeds/checks against this exact list.
TENANT_SCOPED_TABLES = ["lead"]


# gen_random_uuid() is built into Postgres core (>=13), so no extension is needed on
# Neon. created_at is timestamptz so timezones are never ambiguous.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenant (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text NOT NULL UNIQUE,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lead (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       uuid NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name            text,
    email           text,
    problem_summary text,
    source          text NOT NULL DEFAULT 'assistant',
    status          text NOT NULL DEFAULT 'new',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS lead_tenant_idx ON lead (tenant_id);
"""


def rls_policy_statements() -> list[str]:
    """SQL that raises the wall — applied at init time and in the wall test.

    RLS is DEFENSE ONE, not the whole wall. ⚠ Neon's default role (`neondb_owner`) has
    the BYPASSRLS attribute (verified live 2026-09-28: rolbypassrls = true), and a role
    with BYPASSRLS skips row-level security ENTIRELY — even with FORCE. So on Neon these
    policies are NOT self-sufficient; isolation ALSO depends on defense two: every scoped
    query carries an explicit `tenant_id` filter / tag in SQL (create_lead tags the row;
    scoped reads must filter). This is the same conclusion Tinker reached on 2026-09-25
    when a live test caught `neondb_owner` bypassing RLS. See freeze F6 in
    canon/SESSION_CONSTITUTION.md and tests/test_defense_in_depth.py.

    For every tenant-scoped table we:
      1. ENABLE row-level security, and
      2. FORCE it — so the policy applies even to the table owner (without FORCE the
         owner bypasses its own table's RLS). FORCE does NOT override BYPASSRLS, so on
         Neon this is belt-and-suspenders with the explicit tenant_id filters, not a
         standalone wall.
      3. Install a policy that only admits rows whose tenant_id equals the id set for
         the current transaction via set_config('app.tenant_id', <id>, true).

    When the setting is unset, current_setting('app.tenant_id', true) returns an EMPTY
    STRING (a custom GUC reverts to '' after a LOCAL set, not to NULL). ''::uuid would
    throw, so nullif(..., '') maps unset -> NULL -> `tenant_id = NULL` -> ZERO rows: an
    unscoped connection (e.g. a pooled connection between requests) sees nothing —
    safe-by-default, never a leak and never an error.

    The same predicate guards SELECT/UPDATE/DELETE (USING) and INSERT (WITH CHECK), so
    a tenant can neither read, mutate, nor write rows into another tenant.
    """
    stmts: list[str] = []
    for table in TENANT_SCOPED_TABLES:
        policy = f"{table}_tenant_isolation"
        predicate = (
            f"tenant_id = nullif(current_setting('{TENANT_SETTING}', true), '')::uuid"
        )
        stmts.append(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;')
        stmts.append(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY;')
        # Drop-if-exists keeps this idempotent across re-runs.
        stmts.append(f'DROP POLICY IF EXISTS "{policy}" ON "{table}";')
        stmts.append(
            f'CREATE POLICY "{policy}" ON "{table}"\n'
            f"  USING ({predicate})\n"
            f"  WITH CHECK ({predicate});"
        )
    return stmts
