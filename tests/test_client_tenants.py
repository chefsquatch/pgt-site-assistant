"""BRICK 4b — client tenants: a paying local business is a tenant of the engine.

Served behavior, end to end through the routes (route and outcome asserted separately):

  * /t/<slug>/chat answers from THAT business's knowledge folder, and a captured lead is
    stored under THAT tenant only and emailed to ITS owner (copy to PGT);
  * one conversation stores one lead (lead_captured);
  * the owner signs in to their own workspace and sees only their own leads; a session can
    never read another tenant, even with a hand-minted token;
  * /t/ answers any origin (it is embedded on client sites); admin routes keep the allow-list;
  * the public route is rate limited; unknown or malformed slugs 404 and never become paths.

⚠ The app connects as the test database's superuser, which bypasses RLS exactly like Neon's
neondb_owner (BYPASSRLS). So every isolation assertion here holds on defense two alone, the
explicit tenant_id filters/tags (F6). The RLS red control for `lead` is in test_tenant_wall.py
and is unchanged by this brick (no new scoped table).

Runs against TEST_DATABASE_URL; skips cleanly when unset. The model and Resend are stubbed.
"""

from __future__ import annotations

import json
import os

import psycopg
import pytest

from app import assistant, config, corpus, notify
from app.admins import upsert_admin
from app.auth import ADMIN_COOKIE, create_session_token, hash_password
from app.db_schema import SCHEMA_SQL, TENANT_SCOPED_TABLES, rls_policy_statements
from app.leads import list_leads

TEST_DSN = os.getenv("TEST_DATABASE_URL", "").strip()
PW_A = "alpha-owner-pass"
PW_B = "bravo-owner-pass"
OWNER = "owner@biz.test"  # the same email in two tenants: unique only WITHIN a tenant

LEAD = {"name": "Dana Cole", "phone": "810-555-0142", "email": None,
        "summary": "Water heater leaking in the basement", "urgent": False}


def _drop_all(conn) -> None:
    for table in TENANT_SCOPED_TABLES:
        conn.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
    conn.execute("DROP TABLE IF EXISTS tenant CASCADE;")


@pytest.fixture()
def env(monkeypatch, tmp_path):
    if not TEST_DSN:
        pytest.skip("TEST_DATABASE_URL is not set (point it at a Postgres to run the client tests).")
    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setattr(config, "RESEND_API_KEY", "test-key")
    monkeypatch.setattr(config, "CLIENT_RESEND_API_KEY", "client-key")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(config, "LEAD_INBOX", "les@pgt.test")
    monkeypatch.setattr(config, "CLIENT_CHAT_PER_MIN", 100)
    monkeypatch.setattr(config, "CLIENT_CHAT_PER_HOUR", 1000)

    # Each business's knowledge folder. alpha has one; bravo deliberately has none.
    (tmp_path / "alpha").mkdir()
    (tmp_path / "alpha" / "00-about.md").write_text(
        "Alpha Plumbing. Water heater install: $1,200 flat. Hours: Mon-Fri 8-5.", encoding="utf-8")
    monkeypatch.setattr(config, "TENANTS_CORPUS_DIR", tmp_path)
    corpus.load_corpus.cache_clear()

    conn = psycopg.connect(TEST_DSN)
    conn.autocommit = True
    _drop_all(conn)
    conn.execute(SCHEMA_SQL)
    for stmt in rls_policy_statements():
        conn.execute(stmt)
    ids = {}
    for slug, name, notify_email in [("pgt", "PGT", None),
                                     ("alpha", "Alpha Plumbing", "owner@alpha.test"),
                                     ("bravo", "Bravo Salon", "owner@bravo.test")]:
        ids[slug] = conn.execute(
            "INSERT INTO tenant (slug, name, notify_email) VALUES (%s, %s, %s) RETURNING id;",
            (slug, name, notify_email),
        ).fetchone()[0]
    upsert_admin(conn, ids["alpha"], email=OWNER, password_hash=hash_password(PW_A))
    upsert_admin(conn, ids["bravo"], email=OWNER, password_hash=hash_password(PW_B))

    sent = []

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append({**json, "_auth": headers.get("Authorization")})
        return _Resp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)

    from fastapi.testclient import TestClient
    from app import main

    main._client_hits.clear()
    with TestClient(main.app) as c:
        yield {"client": c, "conn": conn, "ids": ids, "sent": sent}

    corpus.load_corpus.cache_clear()
    _drop_all(conn)
    conn.close()


def _stub_model(monkeypatch, payload: dict, seen: list | None = None):
    def fake(system, turns):
        if seen is not None:
            seen.append(system)
        return json.dumps(payload)[1:]  # the turn is prefilled with "{"

    monkeypatch.setattr(assistant, "_call_model", fake)


def _ask(c, slug, text="My water heater is leaking", **extra):
    return c.post(f"/t/{slug}/chat", json={"history": [{"role": "user", "content": text}], **extra})


# --- grounding --------------------------------------------------------------------------

def test_answers_from_that_business_knowledge_only(env, monkeypatch):
    seen = []
    _stub_model(monkeypatch, {"reply": "Install is $1,200 flat.", "in_corpus": True, "lead": None}, seen)
    r = _ask(env["client"], "alpha", "How much to install a water heater?")
    assert r.status_code == 200
    assert r.json()["reply"] == "Install is $1,200 flat."
    assert "Alpha Plumbing" in seen[0] and "$1,200 flat" in seen[0]   # its own knowledge
    assert "Precision Guesswork" not in seen[0]                         # never PGT's corpus


def test_business_without_knowledge_never_calls_the_model(env, monkeypatch):
    def boom(system, turns):
        raise AssertionError("model must not be called without knowledge")

    monkeypatch.setattr(assistant, "_call_model", boom)
    r = _ask(env["client"], "bravo")
    assert r.status_code == 200
    assert "Bravo Salon" in r.json()["reply"] and r.json()["lead"] is None


def test_unknown_or_malformed_slug_is_404_and_never_a_path(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "x", "in_corpus": False, "lead": None})
    assert _ask(env["client"], "nobody").status_code == 404
    assert _ask(env["client"], "Bad_Slug").status_code == 404
    assert _ask(env["client"], "..%2Fcorpus").status_code == 404
    with pytest.raises(ValueError):
        corpus._dir("tenant:../corpus")


# --- the lead: stored under ITS tenant, emailed to ITS owner -----------------------------

def test_lead_is_stored_under_its_tenant_only_and_emailed_to_its_owner(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "Sent! The team will call you.", "in_corpus": True, "lead": LEAD})
    r = _ask(env["client"], "alpha")
    # Route: the customer sees the lead card data.
    assert r.status_code == 200 and r.json()["lead"]["phone"] == "810-555-0142"
    # Outcome: stored under alpha, with the phone, and nowhere else.
    conn, ids = env["conn"], env["ids"]
    alpha = list_leads(conn, ids["alpha"])
    assert [(l["name"], l["phone"], l["problem_summary"]) for l in alpha] == [
        ("Dana Cole", "810-555-0142", "Water heater leaking in the basement")]
    assert list_leads(conn, ids["bravo"]) == [] and list_leads(conn, ids["pgt"]) == []
    # Outcome: one email, to alpha's owner, copy to PGT, with the conversation.
    assert len(env["sent"]) == 1
    mail = env["sent"][0]
    assert mail["to"] == ["owner@alpha.test"] and mail["cc"] == ["les@pgt.test"]
    assert "Dana Cole" in mail["subject"] and "My water heater is leaking" in mail["text"]
    # Sent on the client-alert key (the verified-domain account), not the contact form's.
    assert mail["_auth"] == "Bearer client-key"


def test_urgent_lead_is_marked(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "Sent as urgent.", "in_corpus": True, "lead": {**LEAD, "urgent": True}})
    _ask(env["client"], "alpha")
    assert list_leads(env["conn"], env["ids"]["alpha"])[0]["problem_summary"].startswith("URGENT: ")
    assert env["sent"][0]["subject"].startswith("URGENT ")


def test_one_conversation_stores_one_lead(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "Already sent.", "in_corpus": True, "lead": LEAD})
    _ask(env["client"], "alpha")
    r = _ask(env["client"], "alpha", "thanks!", lead_captured=True)
    assert r.json()["lead"] is None
    assert len(list_leads(env["conn"], env["ids"]["alpha"])) == 1 and len(env["sent"]) == 1


def test_a_lead_without_a_way_to_reach_them_is_not_stored(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "What's your number?", "in_corpus": True,
                              "lead": {"name": "Dana", "phone": None, "email": None, "summary": "x"}})
    assert _ask(env["client"], "alpha").json()["lead"] is None
    assert list_leads(env["conn"], env["ids"]["alpha"]) == [] and env["sent"] == []


def test_a_failed_alert_never_breaks_the_chat_or_loses_the_lead(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "Sent!", "in_corpus": True, "lead": LEAD})

    def down(*a, **k):
        raise RuntimeError("resend is down")

    monkeypatch.setattr(notify.httpx, "post", down)
    r = _ask(env["client"], "alpha")
    assert r.status_code == 200 and r.json()["lead"]["name"] == "Dana Cole"
    assert len(list_leads(env["conn"], env["ids"]["alpha"])) == 1


# --- the owner's workspace -------------------------------------------------------------

def _login(c, workspace, password, email=OWNER):
    return c.post("/admin/login", json={"email": email, "password": password, "workspace": workspace})


def test_owner_signs_in_to_their_workspace_and_sees_only_their_leads(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "Sent!", "in_corpus": True, "lead": LEAD})
    _ask(env["client"], "alpha")
    c = env["client"]
    assert _login(c, "alpha", PW_A).status_code == 200
    assert c.get("/admin/me").json() == {"email": OWNER, "tenant": "alpha"}
    leads = c.get("/admin/leads").json()["leads"]
    assert [l["name"] for l in leads] == ["Dana Cole"]
    c.post("/admin/logout")
    # Same email, other tenant: bravo's password, bravo's (empty) leads.
    assert _login(c, "bravo", PW_B).status_code == 200
    assert c.get("/admin/leads").json()["count"] == 0


def test_wrong_workspace_or_unknown_workspace_is_the_same_401(env):
    c = env["client"]
    assert _login(c, "bravo", PW_A).status_code == 401        # alpha's password in bravo
    assert _login(c, "pgt", PW_A).status_code == 401          # default workspace has no such admin
    r = _login(c, "nobody", PW_A)
    assert r.status_code == 401 and r.json()["error"] == "Invalid email or password."


def test_a_hand_minted_cross_tenant_session_is_rejected(env):
    c = env["client"]
    _login(c, "alpha", PW_A)
    alpha_admin = c.get("/admin/me").json()
    assert alpha_admin["tenant"] == "alpha"
    # Find alpha's admin id, then sign a token claiming bravo's tenant with it.
    conn, ids = env["conn"], env["ids"]
    admin_id = conn.execute("SELECT id FROM admin WHERE tenant_id = %s", (ids["alpha"],)).fetchone()[0]
    forged = create_session_token(str(ids["bravo"]), str(admin_id))
    c.cookies.clear()
    c.cookies.set(ADMIN_COOKIE, forged)
    assert c.get("/admin/leads").status_code == 401  # alpha's admin does not exist inside bravo


# --- embedding + abuse guards ----------------------------------------------------------

def test_client_chat_answers_any_origin_but_admin_keeps_the_allow_list(env):
    c = env["client"]
    pre = {"Origin": "https://some-client-site.com", "Access-Control-Request-Method": "POST",
           "Access-Control-Request-Headers": "content-type"}
    r = c.options("/t/alpha/chat", headers=pre)
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "*"
    r = c.options("/admin/login", headers=pre)
    assert r.headers.get("access-control-allow-origin") != "*"


def test_client_chat_is_rate_limited(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "hi", "in_corpus": False, "lead": None})
    monkeypatch.setattr(config, "CLIENT_CHAT_PER_MIN", 2)
    c = env["client"]
    assert _ask(c, "alpha").status_code == 200
    assert _ask(c, "alpha").status_code == 200
    assert _ask(c, "alpha").status_code == 429


def test_client_widget_is_served(env):
    r = env["client"].get("/client-widget.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert "/t/" in r.text
