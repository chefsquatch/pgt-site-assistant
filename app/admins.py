"""Admin accounts — Brick 3: the tenant-scoped `admin` store.

Ported from Tinker's src/admin/lookup.ts + seedAdmin. Every read/write goes THROUGH
with_tenant() (defense one) AND filters tenant_id in SQL (defense two, F6), so an admin
of one tenant is invisible to another whether or not RLS is enforced. Email is stored
NORMALIZED (trimmed + lowercased) and matched normalized, so login is case-insensitive
and the per-tenant unique index holds.

Password verification is NOT done here — this only finds/creates; app/auth.py verifies.
"""

from __future__ import annotations

from typing import Any

from . import db


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_admin_by_email(conn: db.psycopg.Connection, tenant_id: Any, email: str) -> dict | None:
    """Find an admin by email WITHIN one tenant. Returns {id, email, password_hash} or None."""
    normalized = normalize_email(email)

    def _select(c: db.psycopg.Connection):
        return c.execute(
            "SELECT id, email, password_hash FROM admin "
            "WHERE tenant_id = %s AND email = %s LIMIT 1",
            (tenant_id, normalized),
        ).fetchone()

    row = db.with_tenant(conn, tenant_id, _select)
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1], "password_hash": row[2]}


def find_admin_by_id(conn: db.psycopg.Connection, tenant_id: Any, admin_id: Any) -> dict | None:
    """Find an admin by id WITHIN one tenant. Used to resolve a signed-in session to its
    admin. Returns {id, email} or None (a valid id from another tenant is invisible)."""

    def _select(c: db.psycopg.Connection):
        return c.execute(
            "SELECT id, email FROM admin WHERE tenant_id = %s AND id = %s LIMIT 1",
            (tenant_id, admin_id),
        ).fetchone()

    row = db.with_tenant(conn, tenant_id, _select)
    if row is None:
        return None
    return {"id": str(row[0]), "email": row[1]}


def upsert_admin(
    conn: db.psycopg.Connection, tenant_id: Any, *, email: str, password_hash: str
) -> str:
    """Create the admin, or update its password hash if the (tenant, email) already
    exists. Idempotent so the seed script can be re-run to reset a password. Returns the
    admin id. The row is tagged with tenant_id explicitly (defense two)."""
    normalized = normalize_email(email)

    def _upsert(c: db.psycopg.Connection):
        return c.execute(
            "INSERT INTO admin (tenant_id, email, password_hash) VALUES (%s, %s, %s) "
            "ON CONFLICT (tenant_id, email) DO UPDATE SET password_hash = EXCLUDED.password_hash "
            "RETURNING id",
            (tenant_id, normalized, password_hash),
        ).fetchone()

    row = db.with_tenant(conn, tenant_id, _upsert)
    return str(row[0])
