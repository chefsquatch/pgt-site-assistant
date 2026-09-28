"""BRICK 3 — the `admin` table is walled (F1) and isolated defense-in-depth (F6).

A new tenant-scoped table must ship with its own isolation proof: the wall holds, it is
watched to go red (RLS disabled), and the app's own lookup stays isolated even then
because it filters tenant_id in SQL. Uses the shared `tenants` fixture (A + B).
"""

from __future__ import annotations

from app.admins import find_admin_by_email, upsert_admin
from app.auth import hash_password

PW = "pw-hash-placeholder"


def _seed(harness, tenant_id, email):
    return upsert_admin(harness.conn, tenant_id, email=email, password_hash=hash_password(PW))


# --- the wall HOLDS --------------------------------------------------------------

def test_admin_lookup_is_tenant_scoped(tenants):
    a_id = _seed(tenants, tenants.A, "mgr@a.test")
    _seed(tenants, tenants.B, "mgr@b.test")

    found = find_admin_by_email(tenants.conn, tenants.A, "mgr@a.test")
    assert found is not None and found["id"] == a_id

    # B's admin is invisible inside A's scope.
    assert find_admin_by_email(tenants.conn, tenants.A, "mgr@b.test") is None


def test_email_is_normalized_on_store_and_lookup(tenants):
    a_id = _seed(tenants, tenants.A, "  MixedCase@A.TEST  ")
    # Stored normalized, and lookup normalizes too → case/space-insensitive match.
    assert find_admin_by_email(tenants.conn, tenants.A, "mixedcase@a.test")["id"] == a_id


def test_same_email_distinct_admins_per_tenant(tenants):
    a_id = _seed(tenants, tenants.A, "shared@x.test")
    b_id = _seed(tenants, tenants.B, "shared@x.test")
    assert a_id != b_id
    assert find_admin_by_email(tenants.conn, tenants.A, "shared@x.test")["id"] == a_id
    assert find_admin_by_email(tenants.conn, tenants.B, "shared@x.test")["id"] == b_id


def test_upsert_resets_password_not_duplicates(tenants):
    first = _seed(tenants, tenants.A, "mgr@a.test")
    second = upsert_admin(tenants.conn, tenants.A, email="mgr@a.test", password_hash="new$hash")
    assert first == second  # same row (unique per tenant), password updated in place
    assert find_admin_by_email(tenants.conn, tenants.A, "mgr@a.test")["password_hash"] == "new$hash"


# --- the wall is LOAD-BEARING + defense in depth (F1 red control, F6) ------------

def test_red_control_admin_leaks_raw_but_lookup_isolates(tenants):
    _seed(tenants, tenants.A, "mgr@a.test")
    _seed(tenants, tenants.B, "mgr@b.test")

    # With RLS on and no tenant context, an unscoped read sees zero (safe default).
    assert tenants.conn.execute("SELECT count(*) FROM admin;").fetchone()[0] == 0

    # Pull the wall down — the real prod BYPASSRLS condition. Raw unscoped read leaks BOTH.
    tenants.as_owner('ALTER TABLE "admin" DISABLE ROW LEVEL SECURITY;')
    assert tenants.conn.execute("SELECT count(*) FROM admin;").fetchone()[0] == 2  # the leak

    # But find_admin_by_email filters tenant_id in SQL (defense two), so it STILL isolates
    # with RLS off: B's admin is invisible in A's scope, and vice-versa.
    assert find_admin_by_email(tenants.conn, tenants.A, "mgr@b.test") is None
    assert find_admin_by_email(tenants.conn, tenants.A, "mgr@a.test") is not None

    tenants.as_owner('ALTER TABLE "admin" ENABLE ROW LEVEL SECURITY;')
    tenants.as_owner('ALTER TABLE "admin" FORCE ROW LEVEL SECURITY;')
