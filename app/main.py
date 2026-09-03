"""FastAPI app: the grounded assistant behind the PGT site widget.

Endpoints:
  GET  /            -> a standalone demo page hosting the widget (static/index.html)
  GET  /widget.js   -> the embeddable widget script (served with permissive CORS)
  GET  /health      -> liveness + how many corpus sections are loaded
  POST /chat        -> {history:[{role,content}]} -> {reply,in_corpus,handoff_ready,
                        problem_summary, sources, founder_email}

Every expected failure (missing key, API failure, rate limit, empty message) is
caught and returned as a clean JSON message that includes the email fallback —
never a raw stack trace, never a silent hang, never a fabricated answer.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config, corpus
from .assistant import AssistantError, ConfigError, GenerationError, respond
from .contact import (
    ContactConfigError,
    ContactDeliveryError,
    ContactRequest,
    send_lead,
)

app = FastAPI(title="PGT Site Assistant")


@app.on_event("startup")
def _require_lead_delivery() -> None:
    """Fail loudly at startup if the contact form can't deliver leads — better to
    refuse to boot on a misconfigured deploy than to silently drop the first lead.
    In production RESEND_API_KEY is set in the Render dashboard (like the Anthropic
    key), so this passes and never affects the chat path."""
    if not config.RESEND_API_KEY:
        raise RuntimeError(
            "RESEND_API_KEY is not set — the contact form cannot deliver leads. "
            "Set it in the environment before starting (Render dashboard in prod)."
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class Turn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    history: list[Turn]


def _email_fallback(message: str) -> dict:
    """Every error the visitor sees carries the honest way forward."""
    return {
        "error": message,
        "founder_email": config.FOUNDER_EMAIL,
        "fallback": (
            "Something went wrong on my end — I'd rather tell you than guess. You can "
            f"reach Les directly at {config.FOUNDER_EMAIL}."
        ),
    }


@app.get("/health")
def health() -> dict:
    sections = corpus.corpus_sections()
    return {
        "status": "ok",
        "corpus_sections": sections,
        "corpus_loaded": len(sections),
        "model": config.ANTHROPIC_MODEL,
        "key_present": bool(config.ANTHROPIC_API_KEY),
    }


@app.post("/chat")
def chat(req: ChatRequest) -> JSONResponse:
    history = [{"role": t.role, "content": t.content} for t in req.history]
    try:
        result = respond(history)
    except ConfigError as exc:
        return JSONResponse(status_code=503, content=_email_fallback(str(exc)))
    except GenerationError as exc:
        return JSONResponse(status_code=502, content=_email_fallback(str(exc)))
    except AssistantError as exc:  # empty message, etc.
        return JSONResponse(status_code=400, content=_email_fallback(str(exc)))

    return JSONResponse(
        content={
            "reply": result.reply,
            "in_corpus": result.in_corpus,
            "handoff_ready": result.handoff_ready,
            "problem_summary": result.problem_summary,
            "sources": result.sources,
            "founder_email": config.FOUNDER_EMAIL,
        }
    )


@app.post("/contact")
def contact(req: ContactRequest) -> JSONResponse:
    # Pydantic already rejected malformed/empty/oversized fields with a 422 before
    # we get here — that IS the server-side validation.
    #
    # Honeypot: a filled hidden field means a bot. Accept silently (return the same
    # success shape) and send nothing, so the bot gets no signal it was caught.
    if req.is_bot():
        return JSONResponse(content={"ok": True})

    try:
        send_lead(req)
    except ContactConfigError as exc:
        return JSONResponse(status_code=503, content={"ok": False, "error": str(exc)})
    except ContactDeliveryError as exc:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": (
                    "Sorry — I couldn't send that just now. You can email Les "
                    f"directly at {config.FOUNDER_EMAIL}."
                ),
            },
        )

    return JSONResponse(content={"ok": True})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(config.STATIC_DIR / "index.html"))


@app.get("/widget.js")
def widget() -> FileResponse:
    # Served with the same CORS policy; the site embeds it with a <script> tag.
    return FileResponse(
        str(config.STATIC_DIR / "widget.js"),
        media_type="application/javascript",
    )
