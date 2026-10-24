"""Tinker in-app help (2026-10-24): the /tinker/help endpoint and respond_tinker.

The model call is stubbed (no API spend). These pin the honesty rails: answers come from the
Tinker help corpus (not the PGT services corpus), a bad or ungrounded reply never claims to be
grounded, needs_human carries a summary, and every failure returns a clean reply that points to
PGT support instead of a stack trace.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import assistant, config, corpus
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
ASK = {"history": [{"role": "user", "content": "How do I add an employee?"}]}


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "test-key")
    corpus.load_corpus.cache_clear()
    yield
    corpus.load_corpus.cache_clear()


def _stub(monkeypatch, payload, seen=None):
    def fake(system, turns):
        if seen is not None:
            seen.append(system)
        return payload if isinstance(payload, str) else json.dumps(payload)[1:]  # prefilled "{"

    monkeypatch.setattr(assistant, "_call_model", fake)


def test_answers_from_the_tinker_help_corpus_not_the_site_corpus(monkeypatch):
    seen: list[str] = []
    _stub(monkeypatch, {"reply": "Click + Add employee.", "in_corpus": True, "needs_human": False, "issue_summary": None}, seen)
    r = client.post("/tinker/help", json=ASK)
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Click + Add employee."
    assert body["in_corpus"] is True and body["needs_human"] is False
    assert "Generate join link" in seen[0]  # Tinker help text is in the prompt
    assert "It tracks HOURS, not pay" in seen[0]
    assert "AI RELIABILITY" not in seen[0]  # the site's services prompt is not used


def test_handoff_carries_a_summary(monkeypatch):
    _stub(monkeypatch, {"reply": "Click Email PGT support below.", "in_corpus": False, "needs_human": True,
                        "issue_summary": "The admin reports the report shows zero hours."})
    body = client.post("/tinker/help", json=ASK).json()
    assert body["needs_human"] is True
    assert body["issue_summary"].startswith("The admin reports")


def test_summary_is_dropped_when_no_handoff(monkeypatch):
    _stub(monkeypatch, {"reply": "Steps...", "in_corpus": True, "needs_human": False, "issue_summary": "stray"})
    assert client.post("/tinker/help", json=ASK).json()["issue_summary"] is None


def test_unparseable_reply_is_never_grounded_and_offers_a_human(monkeypatch):
    _stub(monkeypatch, "this is not json at all")
    body = client.post("/tinker/help", json=ASK).json()
    assert body["in_corpus"] is False
    assert body["needs_human"] is True


def test_missing_key_is_a_clean_503_pointing_to_support(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    r = client.post("/tinker/help", json=ASK)
    assert r.status_code == 503
    assert r.json()["needs_human"] is True
    assert "Email PGT support" in r.json()["reply"]


def test_empty_message_is_a_clean_400(monkeypatch):
    r = client.post("/tinker/help", json={"history": []})
    assert r.status_code == 400
    assert r.json()["needs_human"] is True


def test_empty_tinker_corpus_never_calls_the_model(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "TINKER_CORPUS_DIR", tmp_path)
    corpus.load_corpus.cache_clear()

    def boom(system, turns):
        raise AssertionError("model must not be called with no help docs")

    monkeypatch.setattr(assistant, "_call_model", boom)
    body = client.post("/tinker/help", json=ASK).json()
    assert body["needs_human"] is True and body["in_corpus"] is False


def test_tinker_help_has_no_em_dashes():
    text = corpus.load_corpus("tinker")
    assert text, "Tinker help corpus should load"
    assert "—" not in text


def test_site_assistant_still_uses_the_services_corpus(monkeypatch):
    seen: list[str] = []
    _stub(monkeypatch, {"reply": "hi", "in_corpus": False, "handoff_ready": False, "problem_summary": None}, seen)
    r = client.post("/chat", json=ASK)
    assert r.status_code == 200
    assert "AI RELIABILITY" in seen[0]
    assert "Generate join link" not in seen[0]
