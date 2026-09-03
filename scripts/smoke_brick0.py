"""Brick 0 — prove the grounding spine on a 2-line test corpus.

Answers one on-corpus question, refuses one off-corpus question. This does NOT
use the real corpus; it points the loader at a tiny throwaway corpus so we're
testing the MECHANISM before the content exists. Run from the repo root:

    ./.venv/Scripts/python.exe -m scripts.smoke_brick0
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from app import config, corpus


def main() -> int:
    # Point the corpus loader at a 2-line throwaway corpus.
    tmp = Path(tempfile.mkdtemp()) / "corpus"
    tmp.mkdir()
    (tmp / "test.md").write_text(
        "PGT is an independent software studio.\n"
        "PGT's core focus is AI reliability: AI that does not drift or hallucinate.\n",
        encoding="utf-8",
    )
    config.CORPUS_DIR = tmp
    corpus.load_corpus.cache_clear()

    from app.assistant import respond  # import after CORPUS_DIR is patched

    print("Model:", config.ANTHROPIC_MODEL)
    print("Key present:", bool(config.ANTHROPIC_API_KEY))
    print("Corpus sections:", corpus.corpus_sections())
    print("=" * 68)

    # 1) ON-corpus question -> grounded answer.
    on = respond([{"role": "user", "content": "What is PGT's core focus?"}])
    print("Q1 (on-corpus): What is PGT's core focus?")
    print("  in_corpus:", on.in_corpus)
    print("  reply:", on.reply)
    print("-" * 68)

    # 2) OFF-corpus question -> honest refusal, no fabrication.
    off = respond(
        [{"role": "user", "content": "How much does PGT charge for a website?"}]
    )
    print("Q2 (off-corpus): How much does PGT charge for a website?")
    print("  in_corpus:", off.in_corpus)
    print("  reply:", off.reply)
    print("=" * 68)

    ok_on = on.in_corpus and "reliab" in on.reply.lower()
    ok_off = (not off.in_corpus) and (
        "@" in off.reply or "don't have" in off.reply.lower() or "les" in off.reply.lower()
    )
    print("ON-corpus grounded & correct:", ok_on)
    print("OFF-corpus honestly refused :", ok_off)
    ok = ok_on and ok_off
    print("\nBRICK 0:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
