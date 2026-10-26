"""BRICK 7 — human-fork at the honest edges: every edge the assistant can't take further
reaches a person.

Founder GO 2026-10-26 on four pieces, each proven through the routes (route and outcome
asserted separately):

  1. a PGT handoff is stored AND emailed to Les with the conversation (before this brick it
     was only stored, so he saw it only by opening /admin), and still emails when the store
     is down;
  2. the assistant asks for the visitor's email before handing off, so the lead is
     reachable; a missing or junk email is stored as nothing, never as a guess; one
     conversation forks once (handed_off);
  3. a failed turn (no key, model down) leaves an 'edge' lead under the right tenant, so a
     dead conversation still shows up; a bad request does not;
  4. the owner marks a lead handled (or reopens it); waiting leads list first; another
     tenant's lead id is a 404 and is never touched.

No new scoped table (lead's RLS red control is unchanged in test_tenant_wall.py). The app
connects as the superuser, which bypasses RLS like Neon's neondb_owner, so every isolation
assertion here holds on defense two alone, the explicit tenant_id filters (F6).
"""

from __future__ import annotations

import psycopg
import pytest

from app import assistant, db, leads as leads_mod
from app.assistant import GenerationError
from app.leads import create_lead, list_leads, set_lead_status
from test_client_tenants import PW_A, _ask, _login, _stub_model, env  # noqa: F401 (fixture)

SUMMARY = "Their support bot invents refund policies. Stack is a Zendesk plugin."


def _pgt_chat(c, text="Can Les help with this?", **extra):
    return c.post("/chat", json={"history": [{"role": "user", "content": text}], **extra})


def _handoff(**extra):
    return {"reply": "Les has your summary and will reply by email.", "in_corpus": False,
            "handoff_ready": True, "problem_summary": SUMMARY, **extra}


# --- 1 + 2: the PGT handoff reaches Les, with a way to reply -----------------------------

def test_pgt_handoff_is_stored_and_emailed_with_the_visitor_email(env, monkeypatch):
    conn, ids, sent = env["conn"], env["ids"], env["sent"]
    _stub_model(monkeypatch, _handoff(visitor_email="dana@biz.test", visitor_name="Dana"))
    body = _pgt_chat(env["client"]).json()
    # route: the widget is told it was forked, and to whom Les replies
    assert body["forked"] is True and body["visitor_email"] == "dana@biz.test"
    # outcome: stored under PGT only, with the contact
    stored = list_leads(conn, ids["pgt"])
    assert [(l["name"], l["email"], l["problem_summary"], l["status"]) for l in stored] == [
        ("Dana", "dana@biz.test", SUMMARY, "new")]
    assert list_leads(conn, ids["alpha"]) == []
    # outcome: emailed to Les (PGT has no notify_email -> LEAD_INBOX), replyable, with the chat
    assert len(sent) == 1
    assert sent[0]["to"] == ["les@pgt.test"] and sent[0]["reply_to"] == "dana@biz.test"
    assert SUMMARY in sent[0]["text"] and "Customer: Can Les help with this?" in sent[0]["text"]


def test_handoff_without_an_email_still_reaches_les(env, monkeypatch):
    _stub_model(monkeypatch, _handoff(visitor_email=None))
    body = _pgt_chat(env["client"]).json()
    assert body["forked"] is True and body["visitor_email"] is None  # widget shows the form
    assert [l["email"] for l in list_leads(env["conn"], env["ids"]["pgt"])] == [None]
    assert len(env["sent"]) == 1 and "reply_to" not in env["sent"][0]


def test_a_junk_email_is_never_stored(env, monkeypatch):
    _stub_model(monkeypatch, _handoff(visitor_email="their work email", visitor_name="null"))
    body = _pgt_chat(env["client"]).json()
    assert body["visitor_email"] is None
    assert [(l["name"], l["email"]) for l in list_leads(env["conn"], env["ids"]["pgt"])] == [(None, None)]


def test_one_conversation_forks_once(env, monkeypatch):
    _stub_model(monkeypatch, _handoff(visitor_email="dana@biz.test"))
    body = _pgt_chat(env["client"], handed_off=True).json()
    assert body["forked"] is False and body["reply"]  # the visitor still gets the reply
    assert list_leads(env["conn"], env["ids"]["pgt"]) == [] and env["sent"] == []


def test_no_handoff_forks_nothing(env, monkeypatch):
    _stub_model(monkeypatch, {"reply": "What stack are you on?", "in_corpus": False,
                              "handoff_ready": False, "problem_summary": None})
    assert _pgt_chat(env["client"]).json()["forked"] is False
    assert list_leads(env["conn"], env["ids"]["pgt"]) == [] and env["sent"] == []


def test_the_handoff_emails_les_even_when_the_store_is_down(env, monkeypatch):
    def down():
        raise psycopg.OperationalError("store down")

    monkeypatch.setattr(db, "connect", down)
    _stub_model(monkeypatch, _handoff(visitor_email="dana@biz.test"))
    body = _pgt_chat(env["client"]).json()
    assert body["forked"] is True
    assert [m["to"] for m in env["sent"]] == [["les@pgt.test"]]


def test_the_prompt_asks_for_the_email_before_handing_off():
    prompt = assistant._system_prompt()
    assert "Before you hand off, ask once for their email" in prompt
    assert '"visitor_email"' in prompt and '"visitor_name"' in prompt


# --- 3: a failed turn leaves a trace -----------------------------------------------------

def _model_down(monkeypatch):
    def boom(system, turns):
        raise GenerationError("The assistant service failed: overloaded")

    monkeypatch.setattr(assistant, "_call_model", boom)


def test_a_failed_pgt_turn_leaves_an_edge_lead(env, monkeypatch):
    _model_down(monkeypatch)
    r = _pgt_chat(env["client"], text="My agent keeps inventing SKUs")
    assert r.status_code == 502 and "fallback" in r.json()  # the visitor still gets the way out
    stored = list_leads(env["conn"], env["ids"]["pgt"])
    assert [(l["source"], l["status"]) for l in stored] == [("edge", "new")]
    assert "assistant service failed" in stored[0]["problem_summary"]
    assert "My agent keeps inventing SKUs" in stored[0]["problem_summary"]


def test_a_failed_client_turn_leaves_an_edge_lead_under_that_business(env, monkeypatch):
    _model_down(monkeypatch)
    r = _ask(env["client"], "alpha", "Burst pipe in the kitchen")
    assert r.status_code == 502
    stored = list_leads(env["conn"], env["ids"]["alpha"])
    assert [l["source"] for l in stored] == ["edge"]
    assert "Burst pipe in the kitchen" in stored[0]["problem_summary"]
    assert list_leads(env["conn"], env["ids"]["pgt"]) == []
    assert list_leads(env["conn"], env["ids"]["bravo"]) == []


def test_an_unconfigured_assistant_leaves_an_edge_lead(env, monkeypatch):
    monkeypatch.setattr(assistant.config, "ANTHROPIC_API_KEY", "")
    assert _pgt_chat(env["client"]).status_code == 503
    assert [l["source"] for l in list_leads(env["conn"], env["ids"]["pgt"])] == ["edge"]


def test_a_bad_request_is_not_an_edge(env, monkeypatch):
    _model_down(monkeypatch)
    r = env["client"].post("/chat", json={"history": [{"role": "user", "content": "   "}]})
    assert r.status_code == 400
    assert list_leads(env["conn"], env["ids"]["pgt"]) == []


# --- 4: the owner marks a lead handled ---------------------------------------------------

def _lead(conn, tenant_id, summary):
    return create_lead(conn, tenant_id, problem_summary=summary)


def test_waiting_leads_list_first(env):
    conn, a = env["conn"], env["ids"]["alpha"]
    first = _lead(conn, a, "older")
    second = _lead(conn, a, "newer")
    assert set_lead_status(conn, a, second, "handled") is True
    assert [(l["id"], l["status"]) for l in list_leads(conn, a)] == [
        (first, "new"), (second, "handled")]


def test_a_tenant_cannot_mark_another_tenants_lead(env):
    # RLS is bypassed (superuser, the Neon condition): only the tenant_id filter stops this.
    conn, ids = env["conn"], env["ids"]
    theirs = _lead(conn, ids["bravo"], "bravo's lead")
    assert set_lead_status(conn, ids["alpha"], theirs, "handled") is False
    assert [l["status"] for l in list_leads(conn, ids["bravo"])] == ["new"]


def test_status_is_held_to_the_two_values(env):
    conn, a = env["conn"], env["ids"]["alpha"]
    lid = _lead(conn, a, "x")
    with pytest.raises(ValueError):
        set_lead_status(conn, a, lid, "archived")
    with pytest.raises(psycopg.errors.CheckViolation):  # the schema holds it too
        conn.execute("UPDATE lead SET status = 'archived' WHERE id = %s", (lid,))
    assert set_lead_status(conn, a, "not-a-uuid", "handled") is False


def test_status_route_requires_a_signed_in_owner(env):
    lid = _lead(env["conn"], env["ids"]["alpha"], "x")
    r = env["client"].post(f"/admin/leads/{lid}/status", json={"status": "handled"})
    assert r.status_code == 401
    assert [l["status"] for l in list_leads(env["conn"], env["ids"]["alpha"])] == ["new"]


def test_owner_marks_their_lead_handled_and_reopens_it(env):
    c, conn, a = env["client"], env["conn"], env["ids"]["alpha"]
    lid = _lead(conn, a, "x")
    assert _login(c, "alpha", PW_A).status_code == 200
    r = c.post(f"/admin/leads/{lid}/status", json={"status": "handled"})
    assert r.status_code == 200 and r.json() == {"ok": True, "status": "handled"}
    assert [l["status"] for l in c.get("/admin/leads").json()["leads"]] == ["handled"]
    assert c.post(f"/admin/leads/{lid}/status", json={"status": "new"}).status_code == 200
    assert [l["status"] for l in list_leads(conn, a)] == ["new"]


def test_owner_gets_404_for_another_tenants_lead_and_400_for_a_bad_status(env):
    c, conn, ids = env["client"], env["conn"], env["ids"]
    theirs = _lead(conn, ids["bravo"], "bravo's lead")
    mine = _lead(conn, ids["alpha"], "mine")
    assert _login(c, "alpha", PW_A).status_code == 200
    assert c.post(f"/admin/leads/{theirs}/status", json={"status": "handled"}).status_code == 404
    assert [l["status"] for l in list_leads(conn, ids["bravo"])] == ["new"]
    assert c.post(f"/admin/leads/{mine}/status", json={"status": "archived"}).status_code == 400
    assert c.post("/admin/leads/not-a-uuid/status", json={"status": "handled"}).status_code == 404


def test_leads_module_exposes_the_status_set():
    assert leads_mod.LEAD_STATUSES == ("new", "handled")
