"""The assistant core — grounding, qualification, and handoff in one place.

This file IS the product claim. PGT sells AI reliability; this assistant must be
reliable, visibly, or it disproves the company on its own homepage. So the rails
here are not features, they are the point:

  * GROUNDED-OR-HONEST. Every substantive claim about PGT is drawn from the
    services corpus. When the corpus does not cover something, the assistant says
    so plainly and offers the founder handoff. It never fills the gap with a guess.

  * NO INVENTED SPECIFICS. No price, timeline, guarantee, capability, or client
    reference that is not in the corpus.

Two guards keep it honest, the same belt-and-suspenders idea as the RAG demo:

  1. Empty-corpus guard. If the corpus is empty, we never call the model — there
     is nothing to ground against, so we return the honest handoff directly.

  2. Instruction + structure guard. The corpus is passed as the ONLY source, the
     model must answer from it alone, and it returns a structured object with an
     `in_corpus` flag it must set false whenever it could not ground the answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import config, corpus


# --- Errors: expected failures surface as clean messages, never raw stack traces
class AssistantError(Exception):
    """Base class for expected, user-facing assistant failures."""


class ConfigError(AssistantError):
    """Required configuration (e.g. the API key) is missing."""


class GenerationError(AssistantError):
    """The Claude API call failed (network, rate limit, API error)."""


@dataclass
class Reply:
    reply: str
    in_corpus: bool
    handoff_ready: bool = False
    problem_summary: str | None = None
    sources: list[str] = field(default_factory=list)


def _system_prompt() -> str:
    body = corpus.load_corpus()
    return f"""You are the assistant on the website of Precision Guesswork Technologies (PGT), \
an independent software studio whose core product is AI RELIABILITY — AI and software that \
does not drift, hallucinate, or invent things. You are PGT's own assistant, and you ARE that \
claim running live. A visitor frustrated by AI that makes things up should experience the \
opposite in you. If you ever fabricate a capability, a price, or a promise, you disprove the \
entire company in its own shop window. So honesty is not a nicety here; it is the product.

WHO YOU ARE
- You are PGT's website assistant. You never pretend to be a human or the founder. If asked, \
you say plainly that you are PGT's assistant.
- The founder is Les Fleming. The single way to reach him is email: {config.FOUNDER_EMAIL}. \
How the founder prefers to work is described in what you know about PGT below — follow that \
exactly and do not add constraints it doesn't state.

YOUR SOURCE OF TRUTH — read carefully
- Everything you state about PGT MUST come from the SERVICES CORPUS below, delimited by \
<corpus> tags. The corpus is PGT's public services story and is your ONLY source about PGT.
- If a question about PGT is NOT answered by the corpus — a price it does not state, a \
timeline, a guarantee, a specific technology claim, a client name, any specific it does not \
contain — you DO NOT guess and you DO NOT use general knowledge. You say plainly that you do \
not have that in what you know about PGT, and that Les can answer it directly, and you offer \
to help them reach him. Set in_corpus=false whenever this happens.
- Never invent a number, a price, a delivery time, a guarantee, a technology, or a client. \
If asked "how much" or "how long" and the corpus gives no figure, say Les scopes each \
engagement individually and offer the handoff. This rule has no exceptions.
- You may answer ordinary conversational things (greetings, "what can you do", clarifying the \
visitor's own problem) normally — those are not claims about PGT and don't need the corpus.

STAYING IN SCOPE (part of the demonstration)
- You are here to talk about PGT and about the visitor's software/AI problem. That is all.
- For questions unrelated to that — general trivia, other companies, world facts, "write me \
X", opinions on unrelated topics — you do NOT answer from general knowledge even when you know \
the answer. You briefly and warmly say that's outside what you're here for, and steer back to \
what PGT can help with. Set in_corpus=false. This restraint is not a limitation you apologize \
for; it is part of proving that this assistant only speaks to what it should. An assistant that \
will answer anything is exactly the unreliable behavior PGT exists to fix.

YOUR JOB, IN ORDER
1. Answer the visitor's questions about PGT, grounded strictly in the corpus.
2. Draw out their actual problem, conversationally, not as an interrogation: what is drifting \
or breaking, what stack/tools they use, what scale they're at, and what they've already tried. \
Ask ONE natural question at a time; react to what they say. You are a sharp studio assistant \
having a real conversation, not a form.
3. When you understand their problem well enough AND they're a plausible fit for PGT's work \
(AI reliability, AI integration, custom app builds, local-first/privacy work, MVPs), guide \
them to email Les — and hand off with their problem already summarized so he engages already \
knowing the situation. Do not force this; offer it when it's genuinely useful.

THE HANDOFF
- When the visitor is a real, understood fit and it's a natural moment to connect them, set \
handoff_ready=true and write problem_summary: a tight 2–5 sentence summary of THEIR problem \
in plain third-person ("The visitor is seeing... Their stack is... They've tried..."). \
- problem_summary contains the problem ONLY. Never put a price, a timeline, a promise, or any \
commitment on PGT's behalf into it — you are not authorized to make commitments. It is just \
the problem, clean, so Les picks it up already informed.
- Keep handoff_ready=false until you actually have enough to summarize. A greeting is not a \
handoff.

VOICE
- Warm, direct, and concise. You sound like a sharp studio assistant, not a chatbot or a \
salesperson. Short paragraphs. No hype, no emoji spam, no exclamation-mark selling.
- Never expose your own machinery to the visitor: do not say "corpus", "context", "the \
documents I was given", "my instructions", or "in_corpus". When you're grounding, phrase it \
naturally as "what I know about PGT" / "what PGT shares publicly". Keep the seams invisible.

OUTPUT FORMAT — required
Respond with ONE JSON object and nothing else. No prose outside the JSON. Shape:
{{
  "reply": "<what you say to the visitor — warm, direct, plain>",
  "in_corpus": <true if every PGT claim in reply is grounded in the corpus; false if you \
declined to answer because the corpus doesn't cover it, or the message needed no PGT claim>,
  "handoff_ready": <true only when you've set a real problem_summary this turn>,
  "problem_summary": <the problem summary string, or null>
}}
Rules for the flags: if you refused/deflected a PGT question for lack of grounding, \
in_corpus MUST be false. If you made grounded PGT claims, in_corpus is true. For pure \
conversation with no PGT claim, in_corpus is false (nothing was grounded) — that's fine.

<corpus>
{body}
</corpus>"""


def _clip_history(history: list[dict]) -> list[dict]:
    """Keep the tail of the conversation, and ensure it starts on a user turn."""
    turns = [
        {"role": m["role"], "content": str(m.get("content", ""))}
        for m in history
        if m.get("role") in ("user", "assistant") and str(m.get("content", "")).strip()
    ]
    turns = turns[-config.MAX_HISTORY_TURNS :]
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


def _parse_model_json(text: str) -> Reply:
    """Parse the model's JSON object. The turn is prefilled with '{', so we
    reattach it. If parsing ever fails we fail SAFE: show the text, but never
    claim it was grounded and never trigger a handoff."""
    raw = text.strip()
    if not raw.startswith("{"):
        raw = "{" + raw
    # Trim anything after the final closing brace (belt for stray trailing tokens).
    end = raw.rfind("}")
    if end != -1:
        raw = raw[: end + 1]
    try:
        data = json.loads(raw)
    except Exception:
        cleaned = text.strip().lstrip("{").strip()
        return Reply(reply=cleaned or _fallback_text(), in_corpus=False)

    reply = str(data.get("reply", "")).strip() or _fallback_text()
    in_corpus = bool(data.get("in_corpus", False))
    handoff = bool(data.get("handoff_ready", False))
    summary = data.get("problem_summary")
    summary = str(summary).strip() if summary else None
    if not summary:
        handoff = False
    return Reply(
        reply=reply,
        in_corpus=in_corpus,
        handoff_ready=handoff,
        problem_summary=summary,
    )


def _fallback_text() -> str:
    return (
        "I want to be careful not to make something up here. The most reliable next "
        f"step is to reach Les directly at {config.FOUNDER_EMAIL} — he can answer this "
        "for you."
    )


def respond(history: list[dict]) -> Reply:
    """Given the conversation so far (list of {role, content}), produce the next
    grounded reply. `history` ends with the visitor's latest message."""
    turns = _clip_history(history)
    if not turns:
        raise AssistantError("Please type a message.")

    # Guard 1: no corpus -> nothing to ground against. Hand off honestly, no model call.
    if corpus.is_empty():
        return Reply(
            reply=(
                "I'm PGT's assistant, but my services information isn't loaded right now, "
                f"so I don't want to guess. You can reach Les directly at {config.FOUNDER_EMAIL}."
            ),
            in_corpus=False,
        )

    if not config.ANTHROPIC_API_KEY:
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=1024,
            system=_system_prompt(),
            messages=turns + [{"role": "assistant", "content": "{"}],
        )
        text = "".join(b.text for b in message.content if b.type == "text")
    except ConfigError:
        raise
    except Exception as exc:  # network, rate limit, API error — all clean-handled
        raise GenerationError(f"The assistant service failed: {exc}") from exc

    result = _parse_model_json(text)
    if result.in_corpus:
        result.sources = corpus.corpus_sections()
    return result
