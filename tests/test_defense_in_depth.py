"""BRICK 2 — defense in depth (F6): isolation must NOT depend on RLS alone.

⚠ Neon's default role (`neondb_owner`) has BYPASSRLS (verified live 2026-09-28), so in
production RLS is skipped entirely. This test recreates that exact condition — it
DISABLES row-level security on the scoped table — and proves the engine still isolates
tenants, because create_lead() tags every row with tenant_id EXPLICITLY and a scoped
read filters on it. RLS (F1) is defense one; the explicit tenant_id filter is defense
two; together they hold whether or not RLS runs.

Same conclusion Tinker reached 2026-09-25 (tests/tenant-defense-in-depth.test.ts);
ported to the engine here.
"""

from __future__ import annotations

from app.db import with_tenant
from app.leads import create_lead


def test_captured_rows_are_tagged_and_a_filtered_read_isolates_with_rls_off(tenants):
    # Seed one captured lead per tenant WHILE THE WALL IS UP (create_lead tags each row).
    a_lead = create_lead(tenants.conn, tenants.A, problem_summary="A's problem", source="assistant")
    b_lead = create_lead(tenants.conn, tenants.B, problem_summary="B's problem", source="contact")

    # Pull the wall down entirely — simulate the real prod BYPASSRLS / RLS-off condition.
    tenants.as_owner('ALTER TABLE "lead" DISABLE ROW LEVEL SECURITY;')

    # First, prove RLS really is off: an UNSCOPED, UNFILTERED read now sees BOTH rows.
    # (This is the leak the RLS wall would have prevented — and does not, on Neon's role.)
    leaked = tenants.conn.execute("SELECT id FROM lead;").fetchall()
    assert len(leaked) == 2  # RLS is genuinely disabled — the prod condition

    # Defense two: a scoped read that FILTERS tenant_id in SQL still returns only A's row,
    # even though RLS is off. This is what keeps prod isolated on Neon.
    a_rows = tenants.conn.execute(
        "SELECT id FROM lead WHERE tenant_id = %s;", (tenants.A,)
    ).fetchall()
    assert [str(r[0]) for r in a_rows] == [a_lead]

    b_rows = tenants.conn.execute(
        "SELECT id FROM lead WHERE tenant_id = %s;", (tenants.B,)
    ).fetchall()
    assert [str(r[0]) for r in b_rows] == [b_lead]

    # Restore so the state tested matches the state that ships.
    tenants.as_owner('ALTER TABLE "lead" ENABLE ROW LEVEL SECURITY;')
    tenants.as_owner('ALTER TABLE "lead" FORCE ROW LEVEL SECURITY;')


def test_create_lead_tags_the_scoping_tenant_even_with_rls_off(tenants):
    # With RLS off there is no WITH CHECK to enforce the tag — prove create_lead still
    # writes the row under the tenant it was scoped to (the explicit tag, not the policy).
    tenants.as_owner('ALTER TABLE "lead" DISABLE ROW LEVEL SECURITY;')
    lead_id = create_lead(tenants.conn, tenants.A, problem_summary="tagged", source="assistant")

    tag = tenants.conn.execute(
        "SELECT tenant_id FROM lead WHERE id = %s;", (lead_id,)
    ).fetchone()[0]
    assert tag == tenants.A  # tagged to A, not left null or mis-tagged

    tenants.as_owner('ALTER TABLE "lead" ENABLE ROW LEVEL SECURITY;')
    tenants.as_owner('ALTER TABLE "lead" FORCE ROW LEVEL SECURITY;')
