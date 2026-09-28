"""Lead capture — Brick 2: the assistant's captured leads become the system of record.

Brick 1 stood up the tenant-scoped `lead` table and proved the wall. This module is
the seam that WRITES leads into it, and it writes them the only sanctioned way: through
`with_tenant()` (F1). Nothing here touches a scoped table outside that doorway.

Two levels:

  * create_lead()  — the pure write. Given an open connection and a resolved tenant id,
    it inserts one lead THROUGH with_tenant() and returns the new id. This is what the
    wall test exercises directly, so the persistence is proven against a real database.

  * capture_lead() — the best-effort front-door helper the request paths call. It opens
    a connection, resolves PGT (tenant zero), writes, and closes — and it NEVER raises.
    The store is the system of record, but the running assistant must not regress if the
    store is unset (no DATABASE_URL locally) or briefly unreachable: a capture failure is
    logged and swallowed, and the contact path still delivers its email notification, so
    a lead is never lost during the transition off the email-only stopgap. (F4: expand,
    don't regress the proven front.)

The tenant is hardcoded to PGT (tenant zero) for the single-tenant PGT deploy; later
bricks add real per-slug resolution at this same seam.
"""

from __future__ import annotations

import logging
from typing import Any

from . import db
from .db_schema import PGT_TENANT_SLUG

log = logging.getLogger(__name__)


def create_lead(
    conn: db.psycopg.Connection,
    tenant_id: Any,
    *,
    problem_summary: str | None,
    name: str | None = None,
    email: str | None = None,
    source: str = "assistant",
) -> str:
    """Insert one lead for `tenant_id`, THROUGH the wall, and return its id.

    Defense in depth (F6): the row's tenant_id is written EXPLICITLY (defense two), and it
    is the same id with_tenant() binds to app.tenant_id (defense one). So the row is
    correctly tagged whether or not RLS is enforced — which matters because Neon's role
    bypasses RLS. When RLS IS enforced, WITH CHECK additionally rejects a mismatched tag;
    when it is bypassed, the explicit tag is what keeps the row on the right tenant. The
    caller always passes the scoping tenant's own id, so the two can never diverge here.
    """

    def _insert(c: db.psycopg.Connection) -> str:
        row = c.execute(
            "INSERT INTO lead (tenant_id, name, email, problem_summary, source) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (tenant_id, name, email, problem_summary, source),
        ).fetchone()
        return str(row[0])

    return db.with_tenant(conn, tenant_id, _insert)


def capture_lead(
    *,
    problem_summary: str | None,
    name: str | None = None,
    email: str | None = None,
    source: str,
    tenant_slug: str = PGT_TENANT_SLUG,
) -> str | None:
    """Persist a captured lead best-effort. Returns the new lead id, or None if the
    store was unavailable or the write failed. NEVER raises — callers on the request
    path must keep serving the visitor regardless of the store's health."""
    try:
        conn = db.connect()
    except Exception:
        # No DATABASE_URL (e.g. local dev without the store) — nothing to persist to.
        log.info("lead not persisted: store not configured (DATABASE_URL unset)")
        return None

    # Drive the connection in autocommit mode, so each with_tenant() is its own
    # top-level, committed transaction — the exact configuration the wall was proven
    # under. Without this, resolve_tenant() below opens an implicit transaction first,
    # with_tenant()'s transaction() degrades to a nested SAVEPOINT, and conn.close()
    # in the finally rolls the insert back: the lead would look written (RETURNING gave
    # an id) but never persist. This is the seam's contract with the Brick 1 doorway.
    conn.autocommit = True

    try:
        tenant = db.resolve_tenant(conn, tenant_slug)
        if tenant is None:
            log.warning("lead not persisted: tenant slug %r not found in store", tenant_slug)
            return None
        lead_id = create_lead(
            conn,
            tenant["id"],
            problem_summary=problem_summary,
            name=name,
            email=email,
            source=source,
        )
        log.info("lead persisted id=%s source=%s tenant=%s", lead_id, source, tenant_slug)
        return lead_id
    except Exception:
        # A store write failure must not surface to the visitor as a broken assistant.
        log.exception("lead persistence failed (store write error) source=%s", source)
        return None
    finally:
        conn.close()
