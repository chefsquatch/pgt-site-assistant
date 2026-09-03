"""Brick 6 — error handling, forced. Every failure must surface a clean message
plus the email fallback, and NEVER a fabricated answer or a raw stack trace.

We force each failure directly (no real API spend needed) and check the /chat
endpoint's behavior via FastAPI's TestClient.

Run:  ./.venv/Scripts/python.exe -m scripts.smoke_errors
"""

from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from app import assistant, config, corpus
from app.main import app

client = TestClient(app, raise_server_exceptions=False)
EMAIL = config.FOUNDER_EMAIL
results = []


def check(name: str, cond: bool, detail: str = ""):
    results.append(cond)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def post(history):
    return client.post("/chat", json={"history": history})


def main() -> int:
    # 1) Missing API key -> 503, clean message + email fallback, no fabrication.
    saved_key = config.ANTHROPIC_API_KEY
    config.ANTHROPIC_API_KEY = ""
    corpus.load_corpus.cache_clear()
    r = post([{"role": "user", "content": "What does PGT do?"}])
    body = r.json()
    check("missing key -> 503", r.status_code == 503, f"got {r.status_code}")
    check("missing key -> email fallback present", EMAIL in str(body))
    config.ANTHROPIC_API_KEY = saved_key

    # 2) API/generation failure -> 502, clean message + fallback. Force by making
    #    the Anthropic client raise.
    def boom(history):
        raise assistant.GenerationError("The assistant service failed: simulated outage")

    saved_respond = assistant.respond
    import app.main as main_mod
    main_mod.respond = boom
    r = post([{"role": "user", "content": "What does PGT do?"}])
    body = r.json()
    check("API failure -> 502", r.status_code == 502, f"got {r.status_code}")
    check("API failure -> email fallback present", EMAIL in str(body))
    check("API failure -> no stack trace leaked", "Traceback" not in str(body))
    main_mod.respond = saved_respond

    # 3) Empty message -> 400, clean message, not a 500.
    r = post([{"role": "user", "content": "   "}])
    check("empty message -> 400", r.status_code == 400, f"got {r.status_code}")
    check("empty message -> email fallback present", EMAIL in str(r.json()))

    # 4) Empty corpus -> honest handoff, NO model call, no fabrication.
    saved_dir = config.CORPUS_DIR
    from pathlib import Path
    import tempfile
    empty = Path(tempfile.mkdtemp()) / "empty"
    empty.mkdir()
    config.CORPUS_DIR = empty
    corpus.load_corpus.cache_clear()
    out = assistant.respond([{"role": "user", "content": "What does PGT charge?"}])
    check("empty corpus -> honest, not grounded", out.in_corpus is False)
    check("empty corpus -> offers email", EMAIL in out.reply)
    check("empty corpus -> no fabricated price", "$" not in out.reply)
    config.CORPUS_DIR = saved_dir
    corpus.load_corpus.cache_clear()

    print("=" * 60)
    ok = all(results)
    print(f"PASSED {sum(results)}/{len(results)}")
    print("BRICK 6:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
