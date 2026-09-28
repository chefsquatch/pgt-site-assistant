"""BRICK 2 — lead capture into the store, through the wall (F1).

Proves the persistence seam (app/leads.create_lead):

  * a captured lead PERSISTS under its tenant with the fields it was given, and is
    readable inside that tenant's with_tenant scope;
  * it is INVISIBLE to another tenant and to an unscoped connection (safe default);
  * the write is tagged to the scoping tenant — create_lead cannot land a row under
    the wrong tenant;
  * the isolation is LOAD-BEARING (red control): with RLS disabled the captured leads
    leak across the scope, proving the wall — not luck — is what keeps them apart.

Uses the shared `tenants` fixture (A + B, no pre-seeded leads) from conftest.py.
"""

from __future__ import annotations

import os

from app.db import with_tenant
from app.leads import capture_lead, create_lead


# --- the lead PERSISTS -----------------------------------------------------------

def test_captured_lead_persists_under_its_tenant(tenants):
    lead_id = create_lead(
        tenants.conn,
        tenants.A,
        problem_summary="The visitor's RAG bot invents citations. Stack is FastAPI + Chroma.",
        name="Ann Visitor",
        email="ann@example.com",
        source="assistant",
    )

    rows = with_tenant(
        tenants.conn,
        tenants.A,
        lambda c: c.execute(
            "SELECT id, tenant_id, name, email, problem_summary, source, status FROM lead;"
        ).fetchall(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert str(row[0]) == lead_id
    assert row[1] == tenants.A                      # tagged to the scoping tenant
    assert row[2] == "Ann Visitor"
    assert row[3] == "ann@example.com"
    assert row[4].startswith("The visitor's RAG bot")
    assert row[5] == "assistant"
    assert row[6] == "new"                          # schema default status


def test_contact_source_lead_persists_with_minimal_fields(tenants):
    # The contact path passes name/email + message; the assistant path may pass only a
    # summary (name/email null). Prove a summary-only lead persists too.
    lead_id = create_lead(
        tenants.conn,
        tenants.A,
        problem_summary="Summary only — no contact details captured yet.",
        source="assistant",
    )
    rows = with_tenant(
        tenants.conn,
        tenants.A,
        lambda c: c.execute("SELECT id, name, email FROM lead;").fetchall(),
    )
    assert len(rows) == 1
    assert str(rows[0][0]) == lead_id
    assert rows[0][1] is None
    assert rows[0][2] is None


# --- the front-door helper commits (regression: caught the savepoint/rollback bug) --

def test_capture_lead_persists_across_a_fresh_connection(tenants, monkeypatch):
    """capture_lead() is what the request path calls: it opens its OWN connection,
    resolves the tenant, writes, and closes. This proves the write actually COMMITS
    and is visible from a separate connection — the failure mode where capture_lead
    returned an id but conn.close() rolled the insert back (resolve_tenant opened an
    implicit txn, so with_tenant degraded to a nested savepoint)."""
    dsn = os.getenv("TEST_DATABASE_URL", "").strip()
    monkeypatch.setenv("DATABASE_URL", dsn)  # capture_lead opens its own conn from this

    lead_id = capture_lead(
        problem_summary="Front-door capture through the request path.",
        name="Front Door",
        email="fd@example.com",
        source="assistant",
        tenant_slug="alpha",
    )
    assert lead_id is not None  # the helper reports it wrote a lead

    # A DIFFERENT connection (the fixture's) must see the committed row in alpha's scope.
    rows = with_tenant(
        tenants.conn,
        tenants.A,
        lambda c: c.execute("SELECT id, problem_summary, source FROM lead;").fetchall(),
    )
    assert [str(r[0]) for r in rows] == [lead_id]
    assert rows[0][1] == "Front-door capture through the request path."
    assert rows[0][2] == "assistant"


# --- the wall HOLDS for captured leads -------------------------------------------

def test_captured_lead_invisible_to_another_tenant(tenants):
    create_lead(tenants.conn, tenants.A, problem_summary="A's problem", source="assistant")
    rows = with_tenant(
        tenants.conn, tenants.B, lambda c: c.execute("SELECT id FROM lead;").fetchall()
    )
    assert rows == []  # B never sees A's captured lead


def test_captured_lead_unscoped_sees_zero(tenants):
    create_lead(tenants.conn, tenants.A, problem_summary="A's problem", source="assistant")
    # No with_tenant -> app.tenant_id unset -> predicate NULL -> zero rows (safe default).
    rows = tenants.conn.execute("SELECT id FROM lead;").fetchall()
    assert rows == []


# --- the wall is LOAD-BEARING for captured leads (red control) -------------------

def test_red_control_captured_leads_leak_when_rls_disabled(tenants):
    create_lead(tenants.conn, tenants.A, problem_summary="A's problem", source="assistant")
    create_lead(tenants.conn, tenants.B, problem_summary="B's problem", source="contact")

    # With the wall up, A's scope sees only A's captured lead.
    scoped = with_tenant(
        tenants.conn, tenants.A, lambda c: c.execute("SELECT id FROM lead;").fetchall()
    )
    assert len(scoped) == 1

    # Disable RLS and the exact same scoped read returns BOTH captured leads — the leak
    # the wall prevents. Proves the isolation is produced by the policy, not an accident.
    tenants.as_owner('ALTER TABLE "lead" DISABLE ROW LEVEL SECURITY;')
    leaked = with_tenant(
        tenants.conn, tenants.A, lambda c: c.execute("SELECT id FROM lead;").fetchall()
    )
    assert len(leaked) == 2  # <-- the leak

    # Restore so the state tested matches the state that ships.
    tenants.as_owner('ALTER TABLE "lead" ENABLE ROW LEVEL SECURITY;')
    tenants.as_owner('ALTER TABLE "lead" FORCE ROW LEVEL SECURITY;')
