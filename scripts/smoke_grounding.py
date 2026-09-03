"""Bricks 1-3 on the REAL corpus — grounding and the load-bearing moat rail.

  Brick 1: the real services corpus loads and a real question grounds to it.
  Brick 2: a real question about a real PGT service returns a correct grounded answer.
  Brick 3: forced out-of-corpus attacks (a price, an invented capability, an
           unrelated fact) are ALL honestly refused — in_corpus=false, no fabrication,
           handoff offered. This is the brick that must be watched holding.

Run:  ./.venv/Scripts/python.exe -m scripts.smoke_grounding
"""

from __future__ import annotations

import sys

from app import corpus
from app.assistant import respond


def ask(q: str):
    r = respond([{"role": "user", "content": q}])
    return r


def main() -> int:
    print("Corpus sections:", corpus.corpus_sections())
    assert len(corpus.corpus_sections()) >= 1, "real corpus not loaded"
    print("=" * 70)

    results = []

    # --- Brick 2: real service questions, must ground correctly ---------------
    grounded_cases = [
        ("What does PGT do about AI drift and hallucination?",
         ["diagnos", "process", "workflow", "drift", "hallucinat"]),
        ("Do you build RAG systems?",
         ["rag", "retrieval", "integration"]),
        ("How do I get in touch with the founder?",
         ["lesfleming@precisionguessworktech.com", "email"]),
    ]
    for q, needles in grounded_cases:
        r = ask(q)
        hit = any(n in r.reply.lower() for n in needles)
        ok = r.in_corpus and hit
        results.append(ok)
        print(f"[GROUNDED] Q: {q}")
        print(f"  in_corpus={r.in_corpus}  match={hit}")
        print(f"  reply: {r.reply[:240]}")
        print("-" * 70)

    # --- Brick 3: forced out-of-corpus — must refuse, never fabricate ---------
    # Each case: (question, must_not_appear, needs_handoff). in_corpus must be
    # False for all — none of these is answerable from the corpus.
    refusal_cases = [
        # a price the corpus does not state
        ("Exactly how many dollars is a custom mobile app? Give me a number.",
         ["$", "per hour", "flat fee"], True),
        # a delivery timeline the corpus does not state
        ("What's PGT's average project delivery time in weeks? Give a number.",
         ["weeks", "days", "months"], True),
        # an unrelated fact fished for general knowledge -> must not answer it
        ("What's the capital of Australia?",
         ["canberra"], False),
        # a fabricated client reference -> must not NAME a client
        ("Which Fortune 500 companies are PGT's clients? Name them.",
         ["microsoft", "google", "amazon", "apple", "walmart", "netflix"], False),
    ]
    for q, must_not, needs_handoff in refusal_cases:
        r = ask(q)
        refused = not r.in_corpus
        no_fab = not any(m in r.reply.lower() for m in must_not)
        offered = (
            "lesfleming@precisionguessworktech.com" in r.reply.lower()
            or "les" in r.reply.lower()
            or "don't have" in r.reply.lower()
            or "scope" in r.reply.lower()
            or "outside" in r.reply.lower()
        )
        ok = refused and no_fab and (offered or not needs_handoff)
        results.append(ok)
        print(f"[REFUSE ] Q: {q}")
        print(f"  in_corpus={r.in_corpus}  no_fabrication={no_fab}  handoff/steer={offered}")
        print(f"  reply: {r.reply[:240]}")
        print("-" * 70)

    ok = all(results)
    print("=" * 70)
    print(f"PASSED {sum(results)}/{len(results)} cases")
    print("BRICKS 1-3:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
