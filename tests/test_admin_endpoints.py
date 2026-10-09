"""BRICK 3 — the admin auth ENDPOINTS, exercised end-to-end (served behavior, not just
the mechanism). Login sets a signed HttpOnly cookie; the guard admits only a valid
session for THIS tenant; logout clears it.

Runs against a real Postgres (TEST_DATABASE_URL) seeded with the PGT tenant + one admin.
Skips cleanly when TEST_DATABASE_URL is unset.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from app import config
from app.admins import upsert_admin
from app.auth import hash_password
from app.db_schema import SCHEMA_SQL, rls_policy_statements
from app.leads import create_lead

TEST_DSN = os.getenv("TEST_DATABASE_URL", "").strip()

ADMIN_EMAIL = "admin@pgt.test"
ADMIN_PASSWORD = "s3cret-password"


@pytest.fixture()
def client(monkeypatch):
    if not TEST_DSN:
        pytest.skip("TEST_DATABASE_URL is not set (point it at a Postgres to run the endpoint tests).")

    # The app reads these at call time: point it at the test store, keep it OUT of prod
    # mode (so the dev session secret is used and the cookie is not Secure-only over http).
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    # Let the startup lead-delivery guard pass without a real Resend key.
    monkeypatch.setattr(config, "RESEND_API_KEY", "test-key")

    conn = psycopg.connect(TEST_DSN)
    conn.autocommit = True
    conn.execute("DROP TABLE IF EXISTS admin;")
    conn.execute("DROP TABLE IF EXISTS lead;")
    conn.execute("DROP TABLE IF EXISTS tenant;")
    conn.execute(SCHEMA_SQL)
    for stmt in rls_policy_statements():
        conn.execute(stmt)
    pgt_id = conn.execute(
        "INSERT INTO tenant (slug, name) VALUES ('pgt', 'PGT') RETURNING id;"
    ).fetchone()[0]
    upsert_admin(conn, pgt_id, email=ADMIN_EMAIL, password_hash=hash_password(ADMIN_PASSWORD))
    # Seed a couple of leads for PGT + one for another tenant, to prove /admin/leads is scoped.
    create_lead(conn, pgt_id, problem_summary="PGT lead one", source="assistant")
    create_lead(conn, pgt_id, problem_summary="PGT lead two", name="Sam", email="sam@x.test", source="contact")
    other_id = conn.execute(
        "INSERT INTO tenant (slug, name) VALUES ('other', 'Other') RETURNING id;"
    ).fetchone()[0]
    create_lead(conn, other_id, problem_summary="OTHER tenant lead", source="assistant")
    conn.close()

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c

    conn = psycopg.connect(TEST_DSN)
    conn.autocommit = True
    conn.execute("DROP TABLE IF EXISTS admin;")
    conn.execute("DROP TABLE IF EXISTS lead;")
    conn.execute("DROP TABLE IF EXISTS tenant;")
    conn.close()


def test_login_wrong_password_is_401(client):
    r = client.post("/admin/login", json={"email": ADMIN_EMAIL, "password": "nope"})
    assert r.status_code == 401
    assert r.json()["ok"] is False
    assert "pgt_admin" not in r.cookies  # no session handed out


def test_login_unknown_email_is_401(client):
    r = client.post("/admin/login", json={"email": "ghost@pgt.test", "password": ADMIN_PASSWORD})
    assert r.status_code == 401


def test_me_without_cookie_is_401(client):
    assert client.get("/admin/me").status_code == 401


def test_login_then_me_then_logout(client):
    r = client.post("/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "email": ADMIN_EMAIL}

    # The signed cookie is now on the client — the guard admits it and reports who + where.
    me = client.get("/admin/me")
    assert me.status_code == 200
    assert me.json() == {"email": ADMIN_EMAIL, "tenant": "pgt"}

    # Logout clears the cookie → the guard denies again.
    assert client.post("/admin/logout").status_code == 200
    assert client.get("/admin/me").status_code == 401


def test_login_is_case_insensitive_on_email(client):
    r = client.post("/admin/login", json={"email": "  Admin@PGT.test ", "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --- Brick 4: the admin view ------------------------------------------------------

def test_admin_leads_requires_auth(client):
    assert client.get("/admin/leads").status_code == 401


def test_admin_leads_returns_only_this_tenant(client):
    client.post("/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    r = client.get("/admin/leads")
    assert r.status_code == 200
    data = r.json()
    summaries = [l["problem_summary"] for l in data["leads"]]
    assert data["count"] == 2
    assert set(summaries) == {"PGT lead one", "PGT lead two"}
    assert "OTHER tenant lead" not in summaries  # the other tenant's lead is never shown


def test_admin_page_is_served(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Captured leads" in r.text  # the page shell renders (data loads client-side)
