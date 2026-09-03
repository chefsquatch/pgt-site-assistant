"""Brick 2 — /contact endpoint, server-side. Every bad case is FORCED by hitting
the endpoint directly (frontend bypassed), so client-side checks can't be the
thing under test. Each red is watched before green.

  malformed email        -> 422 (rejected server-side)
  empty email            -> 422
  empty message          -> 422
  oversized payload       -> 422 (length cap holds)
  honeypot filled        -> 200 ok, and NOTHING is sent (silent spam reject)
  missing RESEND_API_KEY -> app refuses to boot (fails at startup, not on 1st lead)
  valid submission       -> 200 ok, Resend called with reply_to = the submitter

The real Resend HTTP call is stubbed here (no live send / no key needed); the
one proof this can't make on its own — the email actually landing in Les's inbox
— needs the founder's real key and a live submission.

Run:  ./.venv/Scripts/python.exe -m scripts.smoke_contact
"""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app import config, contact, main

results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def main_run() -> int:
    # Let the app boot for the endpoint tests (real key not needed; the send is stubbed).
    config.RESEND_API_KEY = "test_dummy_key"

    # Capture what would be sent to Resend, without touching the network.
    sent = []

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.append({"url": url, "json": json, "headers": headers})
        return _Resp()

    contact.httpx.post = fake_post  # stub the delivery call

    with TestClient(main.app) as client:
        # --- validation rejections (422) --------------------------------------
        r = client.post("/contact", json={"email": "not-an-email", "message": "hi there"})
        check("malformed email -> 422", r.status_code == 422, f"got {r.status_code}")

        r = client.post("/contact", json={"email": "", "message": "hi there"})
        check("empty email -> 422", r.status_code == 422, f"got {r.status_code}")

        r = client.post("/contact", json={"email": "a@b.com", "message": "   "})
        check("empty message -> 422", r.status_code == 422, f"got {r.status_code}")

        r = client.post("/contact", json={"email": "a@b.com", "message": "x" * 5001})
        check("oversized message -> 422", r.status_code == 422, f"got {r.status_code}")

        # --- honeypot: accepted silently, nothing sent ------------------------
        sent.clear()
        r = client.post(
            "/contact",
            json={"email": "bot@spam.com", "message": "buy stuff", "company": "AcmeBot"},
        )
        body = r.json()
        check("honeypot -> 200 ok", r.status_code == 200 and body.get("ok") is True,
              f"got {r.status_code} {body}")
        check("honeypot -> nothing sent", len(sent) == 0, f"sent={len(sent)}")

        # --- valid submission: accepted, Resend called with reply-to ----------
        sent.clear()
        r = client.post(
            "/contact",
            json={
                "email": "lead@example.com",
                "name": "Dana Lead",
                "message": "We have Claude drift on a Next.js app.",
            },
        )
        body = r.json()
        check("valid -> 200 ok", r.status_code == 200 and body.get("ok") is True,
              f"got {r.status_code} {body}")
        check("valid -> Resend called once", len(sent) == 1, f"sent={len(sent)}")
        if sent:
            p = sent[0]["json"]
            check("valid -> reply_to = submitter", p.get("reply_to") == "lead@example.com",
                  f"reply_to={p.get('reply_to')}")
            check("valid -> to = lead inbox", p.get("to") == [config.LEAD_INBOX],
                  f"to={p.get('to')}")
            check("valid -> message + email in body",
                  "drift on a Next.js" in p.get("text", "") and "lead@example.com" in p.get("text", ""))
            check("valid -> Authorization bearer set",
                  sent[0]["headers"].get("Authorization") == "Bearer test_dummy_key")

    # --- missing key -> app refuses to boot (fails at startup) ----------------
    config.RESEND_API_KEY = ""
    startup_failed = False
    try:
        with TestClient(main.app):
            pass  # entering the context runs the startup event
    except Exception as exc:
        startup_failed = "RESEND_API_KEY" in str(exc)
    check("missing RESEND_API_KEY -> fails at startup", startup_failed)
    config.RESEND_API_KEY = "test_dummy_key"  # restore

    print("=" * 62)
    ok = all(results)
    print(f"PASSED {sum(results)}/{len(results)}")
    print("BRICK 2:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main_run())
