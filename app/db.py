"""The tenant-scoped store — Brick 1 (the load-bearing wall).

This is the single doorway through which tenant-scoped data is touched, ported
faithfully from Tinker's src/db/rls.ts (withTenant) and src/tenant/resolve.ts. The
wall itself lives in the database (see db_schema.py); this module is how the app
passes through it correctly.

The chat and contact paths do NOT import this module yet — Brick 1 stands up the
store and proves the wall; Brick 2 is what wires the assistant to write leads through
with_tenant(). Keeping this seam separate means adding the store cannot regress the
running assistant.
"""

from __future__ import annotations

import os
from typing import Any, Callable, TypeVar

import psycopg

from .db_schema import TENANT_SETTING

R = TypeVar("R")


def connect(dsn: str | None = None) -> psycopg.Connection:
    """Open a connection to the store. DATABASE_URL is required (Neon in prod).

    .strip() for the same pasted-whitespace reason as the API keys in config.py.
    node-postgres/psycopg give REAL multi-statement transactions, which the RLS model
    requires (set_config LOCAL to a txn, then the scoped queries in that same txn) —
    the Neon HTTP driver does not, and using it would silently break the wall.
    """
    dsn = (dsn or os.getenv("DATABASE_URL", "")).strip()
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL is not set — the engine's store cannot connect. "
            "Set it in the environment (Neon connection string in prod)."
        )
    return psycopg.connect(dsn)


def with_tenant(
    conn: psycopg.Connection,
    tenant_id: Any,
    fn: Callable[[psycopg.Connection], R],
) -> R:
    """Run `fn` inside a transaction scoped to exactly one tenant.

    set_config(..., true) sets app.tenant_id LOCAL to this transaction, so the scope is
    torn down when the txn ends and can never leak onto the next query on a pooled
    connection. Inside `fn`, every query against a tenant-scoped table is filtered by
    the RLS policy to this tenant's rows — the DB enforces it, not us.

    This is the single doorway through which tenant-scoped data is touched. When RLS is
    enforced, a query outside a with_tenant txn has app.tenant_id unset, the predicate is
    NULL, and it admits ZERO rows — safe by default.

    ⚠ DEFENSE ONE ONLY. RLS is bypassed entirely by a role with BYPASSRLS, which is
    exactly what Neon's default `neondb_owner` has. So with_tenant's DB-enforced scoping
    is NOT sufficient on Neon on its own: every scoped query must ALSO carry an explicit
    tenant_id filter/tag in SQL (defense two — freeze F6). create_lead tags the row it
    inserts; scoped reads (Brick 4+) MUST filter `WHERE tenant_id = ...`. Belt and
    suspenders: keep with_tenant AND filter, so isolation holds whether or not RLS runs.
    """
    with conn.transaction():
        # Bind as a parameter so the id can never be interpolated into SQL text.
        conn.execute("SELECT set_config(%s, %s, true)", (TENANT_SETTING, str(tenant_id)))
        return fn(conn)


def resolve_tenant(conn: psycopg.Connection, slug: str) -> dict[str, Any] | None:
    """Resolve a URL slug to its tenant, or None for an unknown slug (caller 404s).

    The `tenant` table is not tenant-scoped — it is the directory of tenants — so this
    lookup runs OUTSIDE with_tenant(). Everything the resolved tenant then touches goes
    THROUGH with_tenant(conn, tenant['id'], ...).
    """
    row = conn.execute(
        "SELECT id, slug, name FROM tenant WHERE slug = %s LIMIT 1", (slug,)
    ).fetchone()
    if row is None:
        return None
    return {"id": row[0], "slug": row[1], "name": row[2]}
