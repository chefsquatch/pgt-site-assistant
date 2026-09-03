"""Bricks 4-5 — qualification and handoff, on a mock prospect conversation.

Simulates a real prospect describing a drift problem across several turns, and
checks:
  Brick 4: the assistant draws out the problem (symptom, stack, scale, tried) and,
           by the end, has enough to summarize it.
  Brick 5: it produces a clean problem_summary and routes to email, with NO invented
           commitments (no price, no timeline, no guarantee) in the summary.

Run:  ./.venv/Scripts/python.exe -m scripts.smoke_handoff
"""

from __future__ import annotations

import sys

from app.assistant import respond

# A scripted prospect. Each line is the visitor's next message; the assistant's
# replies are appended to history between them so it's a real multi-turn chat.
PROSPECT_TURNS = [
    "Hi — our Claude coding setup keeps going off the rails and I'm losing my mind.",
    "It forgets the spec halfway through a task and starts refactoring files we "
    "didn't touch. We're a 5-person team shipping a Next.js app.",
    "We've tried longer system prompts and a cursor rules file. Helps a little, "
    "then it drifts again on big tasks.",
    "Yeah, I'd love to get this in front of Les. What's the best way?",
]

# Words that would signal an invented commitment leaking into the summary.
FORBIDDEN_IN_SUMMARY = [
    "$", "guarantee", "guaranteed", "within a week", "in 2 weeks", "by friday",
    "free", "discount", "we will deliver", "we promise", "fixed price",
]


def main() -> int:
    history: list[dict] = []
    last = None
    drew_out = False

    for i, msg in enumerate(PROSPECT_TURNS, 1):
        history.append({"role": "user", "content": msg})
        r = respond(history)
        history.append({"role": "assistant", "content": r.reply})
        last = r
        print(f"VISITOR: {msg}")
        print(f"ASSISTANT: {r.reply}")
        print(f"   [in_corpus={r.in_corpus} handoff_ready={r.handoff_ready}]")
        # Somewhere in the middle it should be asking to draw the problem out.
        if i in (1, 2) and "?" in r.reply:
            drew_out = True
        print("-" * 70)

    print("=" * 70)
    summary = (last.problem_summary or "") if last else ""
    print("FINAL handoff_ready:", last.handoff_ready if last else None)
    print("FINAL problem_summary:", summary)
    print("FINAL reply has email:",
          "lesfleming@precisionguessworktech.com" in (last.reply.lower() if last else ""))

    has_summary = bool(summary.strip())
    handoff = bool(last and last.handoff_ready)
    # Summary should capture the actual problem shape.
    captures = any(w in summary.lower() for w in ["drift", "spec", "refactor", "next.js", "claude"])
    routes_email = "lesfleming@precisionguessworktech.com" in (last.reply.lower() if last else "")
    no_commitment = not any(w in summary.lower() for w in FORBIDDEN_IN_SUMMARY)

    print("-" * 70)
    print("Brick 4 — drew out the problem (asked questions):", drew_out)
    print("Brick 4 — usable summary produced:", has_summary and captures)
    print("Brick 5 — handoff_ready set:", handoff)
    print("Brick 5 — routed to email:", routes_email)
    print("Brick 5 — NO invented commitment in summary:", no_commitment)

    ok = drew_out and has_summary and captures and handoff and routes_email and no_commitment
    print("\nBRICKS 4-5:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
