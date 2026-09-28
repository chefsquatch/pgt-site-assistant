"""BRICK 1 — the load-bearing wall (F1): one tenant can never read another's rows.

The Python mirror of Tinker's tests/tenant-scoping.test.ts. It seeds two tenants
(A + B), each with one lead, and proves:

  * the wall HOLDS   — A sees only A's lead, cannot reach B's even by exact id, an
                       unscoped connection sees zero rows, and A cannot INSERT a row
                       tagged for B (WITH CHECK).
  * the wall is LOAD-BEARING (the red control) — with RLS disabled, B leaks into A's
                       scope. This proves the isolation above is produced by the
                       policy, not by an accident (e.g. a query that happens to return
                       nothing). A test nobody has watched go red is a claim.

Substrate + the A/B harness (the `h` fixture) live in tests/conftest.py, shared with
the lead-capture suite. `h` yields tenants A and B each seeded with one lead.
"""

from __future__ import annotations

import psycopg
import pytest

from app.db import resolve_tenant, with_tenant


# --- slug resolution -------------------------------------------------------------

def test_resolves_known_slug(h):
    t = resolve_tenant(h.conn, "alpha")
    assert t is not None
    assert t["id"] == h.A
    assert t["name"] == "Alpha Co"


def test_unknown_slug_is_none(h):
    assert resolve_tenant(h.conn, "nope") is None


# --- the wall HOLDS --------------------------------------------------------------

def test_tenant_reads_only_its_own_leads(h):
    rows = with_tenant(h.conn, h.A, lambda c: c.execute("SELECT id FROM lead;").fetchall())
    assert len(rows) == 1
    assert rows[0][0] == h.a_lead


def test_cannot_read_another_tenants_row_even_by_exact_id(h):
    rows = with_tenant(
        h.conn,
        h.A,
        lambda c: c.execute("SELECT id FROM lead WHERE id = %s;", (h.b_lead,)).fetchall(),
    )
    assert rows == []  # B's row is invisible inside A's scope


def test_no_tenant_context_sees_zero_rows(h):
    # No with_tenant -> app.tenant_id unset -> predicate NULL -> zero rows (safe default).
    rows = h.conn.execute("SELECT id FROM lead;").fetchall()
    assert rows == []


def test_cannot_insert_a_row_tagged_for_another_tenant(h):
    # Inside A's scope, try to smuggle a row tagged for B. WITH CHECK must reject it.
    with pytest.raises(psycopg.Error):
        with_tenant(
            h.conn,
            h.A,
            lambda c: c.execute(
                "INSERT INTO lead (tenant_id, name) VALUES (%s, 'smuggled');", (h.B,)
            ),
        )


# --- the wall is LOAD-BEARING (red control) --------------------------------------

def test_red_control_with_rls_disabled_B_leaks_into_A(h):
    # Prove the isolation above is produced by the RLS policy, not by an accident.
    # Disable RLS on the table and the exact same scoped query returns BOTH rows.
    h.as_owner('ALTER TABLE "lead" DISABLE ROW LEVEL SECURITY;')
    rows = with_tenant(h.conn, h.A, lambda c: c.execute("SELECT id FROM lead;").fetchall())
    assert len(rows) == 2  # <-- the leak the wall prevents
    # Restore so the state tested matches the state that ships.
    h.as_owner('ALTER TABLE "lead" ENABLE ROW LEVEL SECURITY;')
    h.as_owner('ALTER TABLE "lead" FORCE ROW LEVEL SECURITY;')
