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

Substrate: a Neon test branch, via TEST_DATABASE_URL. Neon connects as a
non-superuser that owns these tables, so FORCE ROW LEVEL SECURITY binds this
connection as-is and the owner can still toggle RLS for the red control. If the
connection happens to be a superuser (e.g. a local Postgres), the fixture switches to
a NOSUPERUSER role for the scoped queries so the wall is enforced exactly as on Neon,
and runs the red control's DDL back as the owner (mirroring Tinker's asOwner).
"""

from __future__ import annotations

import os

import psycopg
import pytest

from app.db import resolve_tenant, with_tenant
from app.db_schema import SCHEMA_SQL, rls_policy_statements

TEST_DSN = os.getenv("TEST_DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL is not set (point it at a Neon test branch to run the wall test).",
)

APP_ROLE = "pgt_app_test"


class Harness:
    """A fresh, RLS-walled store seeded with tenants A and B, one lead each."""

    def __init__(self, conn: psycopg.Connection, switched: bool):
        self.conn = conn
        self._switched = switched

    def as_owner(self, raw_sql: str) -> None:
        """Run privileged DDL (the red control's RLS toggle) as the table owner."""
        if self._switched:
            self.conn.execute("RESET ROLE;")
            self.conn.execute(raw_sql)
            self.conn.execute(f"SET ROLE {APP_ROLE};")
        else:
            self.conn.execute(raw_sql)
        self.conn.commit()


@pytest.fixture()
def h():
    conn = psycopg.connect(TEST_DSN)
    conn.autocommit = True  # DDL/seed run outside the with_tenant txns

    # Clean slate each run so the test is idempotent on a reused branch.
    conn.execute("DROP TABLE IF EXISTS lead;")
    conn.execute("DROP TABLE IF EXISTS tenant;")
    conn.execute(SCHEMA_SQL)
    for stmt in rls_policy_statements():
        conn.execute(stmt)

    # If we're a superuser, RLS (even FORCE) is bypassed — switch to a non-superuser
    # role for the scoped queries so the wall is enforced exactly as it is on Neon.
    is_super = conn.execute(
        "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
    ).fetchone()[0]
    switched = False
    if is_super:
        conn.execute(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') "
            f"THEN CREATE ROLE {APP_ROLE} NOSUPERUSER; END IF; END $$;"
        )
        conn.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {APP_ROLE};")
        conn.execute(f"SET ROLE {APP_ROLE};")
        switched = True

    # tenant is the directory table (not scoped) — seed it directly.
    a_id = conn.execute(
        "INSERT INTO tenant (slug, name) VALUES ('alpha', 'Alpha Co') RETURNING id;"
    ).fetchone()[0]
    b_id = conn.execute(
        "INSERT INTO tenant (slug, name) VALUES ('bravo', 'Bravo Co') RETURNING id;"
    ).fetchone()[0]

    # Seed each tenant's lead through the doorway — this also exercises the write path.
    a_lead = with_tenant(
        conn,
        a_id,
        lambda c: c.execute(
            "INSERT INTO lead (tenant_id, name) VALUES (%s, 'Ann (A)') RETURNING id;",
            (a_id,),
        ).fetchone()[0],
    )
    b_lead = with_tenant(
        conn,
        b_id,
        lambda c: c.execute(
            "INSERT INTO lead (tenant_id, name) VALUES (%s, 'Bob (B)') RETURNING id;",
            (b_id,),
        ).fetchone()[0],
    )

    harness = Harness(conn, switched)
    harness.A = a_id
    harness.B = b_id
    harness.a_lead = a_lead
    harness.b_lead = b_lead
    yield harness

    if switched:
        conn.execute("RESET ROLE;")
    conn.execute("DROP TABLE IF EXISTS lead;")
    conn.execute("DROP TABLE IF EXISTS tenant;")
    conn.close()


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
