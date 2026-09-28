"""Shared test substrate for the tenant wall (Brick 1) and lead capture (Brick 2).

Both suites need the same thing: a fresh, RLS-walled store with two tenants (A + B) so
isolation can be proven and watched to go red. That harness lives here so neither suite
duplicates it.

Substrate: any Postgres, via TEST_DATABASE_URL. Neon connects as a non-superuser that
owns these tables, so FORCE ROW LEVEL SECURITY binds this connection as-is and the owner
can still toggle RLS for the red control. If the connection happens to be a superuser
(e.g. a local Postgres), the fixture switches to a NOSUPERUSER role for the scoped
queries so the wall is enforced exactly as on Neon, and runs the red control's DDL back
as the owner (mirroring Tinker's asOwner). If TEST_DATABASE_URL is unset, the fixtures
skip cleanly.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from app.db import with_tenant
from app.db_schema import SCHEMA_SQL, rls_policy_statements

TEST_DSN = os.getenv("TEST_DATABASE_URL", "").strip()

APP_ROLE = "pgt_app_test"


class Harness:
    """A fresh, RLS-walled store seeded with tenants A and B.

    `tenants` yields it with A and B set (no leads); the `h` fixture layers on one
    seeded lead per tenant for the wall test.
    """

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
def tenants():
    """Fresh RLS-walled store with tenants A and B and no leads."""
    if not TEST_DSN:
        pytest.skip("TEST_DATABASE_URL is not set (point it at a Postgres to run the wall tests).")

    conn = psycopg.connect(TEST_DSN)
    conn.autocommit = True  # DDL/seed run outside the with_tenant txns

    # Clean slate each run so the tests are idempotent on a reused database.
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

    harness = Harness(conn, switched)
    harness.A = a_id
    harness.B = b_id
    yield harness

    if switched:
        conn.execute("RESET ROLE;")
    conn.execute("DROP TABLE IF EXISTS lead;")
    conn.execute("DROP TABLE IF EXISTS tenant;")
    conn.close()


@pytest.fixture()
def h(tenants):
    """The wall-test harness: tenants A and B, each with one seeded lead."""
    a_lead = with_tenant(
        tenants.conn,
        tenants.A,
        lambda c: c.execute(
            "INSERT INTO lead (tenant_id, name) VALUES (%s, 'Ann (A)') RETURNING id;",
            (tenants.A,),
        ).fetchone()[0],
    )
    b_lead = with_tenant(
        tenants.conn,
        tenants.B,
        lambda c: c.execute(
            "INSERT INTO lead (tenant_id, name) VALUES (%s, 'Bob (B)') RETURNING id;",
            (tenants.B,),
        ).fetchone()[0],
    )
    tenants.a_lead = a_lead
    tenants.b_lead = b_lead
    return tenants
