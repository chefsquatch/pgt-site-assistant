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

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import config, corpus, db
from .admins import find_admin_by_email, find_admin_by_id
from .assistant import AssistantError, ConfigError, GenerationError, respond
from .auth import (
    ADMIN_COOKIE,
    SESSION_TTL_MS,
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)
from .contact import (
    ContactConfigError,
    ContactDeliveryError,
    ContactRequest,
    send_lead,
)
from .db_schema import PGT_TENANT_SLUG
from .leads import capture_lead

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


# GET and HEAD: uptime monitors (UptimeRobot etc.) ping with HEAD by default;
# answering it 200 keeps the free instance warm without false "down" alerts.
@app.api_route("/health", methods=["GET", "HEAD"])
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

    # System of record: when the assistant has qualified a visitor and summarized their
    # problem, persist it as a lead (source='assistant'). Best-effort — capture_lead
    # never raises, so a store hiccup can't break the reply the visitor is waiting on.
    if result.handoff_ready and result.problem_summary:
        capture_lead(problem_summary=result.problem_summary, source="assistant")

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

    # System of record first: persist the lead through the tenant wall (source='contact').
    # Best-effort — if the store is unset/unreachable, capture_lead logs and returns None,
    # and the email below still delivers, so no lead is lost during the transition off the
    # email-only stopgap. The email stays as the founder's notification (store = truth).
    capture_lead(
        problem_summary=req.message,
        name=req.name,
        email=str(req.email),
        source="contact",
    )

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


# --- Admin auth (Brick 3) ------------------------------------------------------------
# Single-tenant deploy: the admin is PGT's (tenant zero). Auth is NOT best-effort like
# lead capture — it FAILS CLOSED: if the store is unreachable or the session secret is
# missing in prod, login and the guard deny rather than admit.

# Cookies get the Secure flag in production (Render serves HTTPS); off locally so dev
# over http still works. Set once at import from Render's own env signal.
_COOKIE_SECURE = bool(os.getenv("RENDER"))

# A constant hash to verify against when no admin matches, so a wrong EMAIL and a wrong
# PASSWORD take the same time — no user-enumeration timing signal.
_DUMMY_PASSWORD_HASH = hash_password("timing-equalizer-not-a-real-account")


class AdminLoginRequest(BaseModel):
    email: str
    password: str


def _open_store() -> db.psycopg.Connection:
    """Open an autocommit connection for an auth operation (same contract as the lead
    seam: autocommit so each with_tenant is its own committed transaction)."""
    conn = db.connect()
    conn.autocommit = True
    return conn


def require_admin(request: Request) -> dict:
    """FastAPI dependency: admit only a request carrying a valid session cookie for THIS
    deploy's tenant (PGT). The session-layer wall — session.tenant_id == the resolved
    tenant id — is enforced here (port of Tinker's session-guard). Raises 401 otherwise,
    503 if the store/secret is unavailable."""
    token = request.cookies.get(ADMIN_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in.")
    try:
        session = verify_session_token(token)
    except RuntimeError:  # ADMIN_SESSION_SECRET missing in prod — cannot verify
        raise HTTPException(status_code=503, detail="Admin sessions are not configured.")
    if session is None:
        raise HTTPException(status_code=401, detail="Session invalid or expired.")

    try:
        conn = _open_store()
    except Exception:
        raise HTTPException(status_code=503, detail="The store is unavailable.")
    try:
        tenant = db.resolve_tenant(conn, PGT_TENANT_SLUG)
        # The session-layer wall: a cookie minted for another tenant is inert here.
        if tenant is None or session.tenant_id != str(tenant["id"]):
            raise HTTPException(status_code=401, detail="Session invalid for this workspace.")
        admin = find_admin_by_id(conn, tenant["id"], session.admin_id)
        if admin is None:
            raise HTTPException(status_code=401, detail="Admin no longer exists.")
        return {"tenant": tenant, "admin": admin}
    finally:
        conn.close()


@app.post("/admin/login")
def admin_login(req: AdminLoginRequest) -> JSONResponse:
    try:
        conn = _open_store()
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "error": "The store is unavailable."})
    try:
        tenant = db.resolve_tenant(conn, PGT_TENANT_SLUG)
        if tenant is None:
            return JSONResponse(status_code=503, content={"ok": False, "error": "No workspace configured."})
        account = find_admin_by_email(conn, tenant["id"], req.email)
    finally:
        conn.close()

    # Always run a verification so a missing account costs the same time as a wrong password.
    stored = account["password_hash"] if account else _DUMMY_PASSWORD_HASH
    if not verify_password(req.password, stored) or account is None:
        return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid email or password."})

    try:
        token = create_session_token(str(tenant["id"]), account["id"])
    except RuntimeError:  # ADMIN_SESSION_SECRET missing in prod
        return JSONResponse(status_code=503, content={"ok": False, "error": "Admin sessions are not configured."})

    resp = JSONResponse(content={"ok": True, "email": account["email"]})
    resp.set_cookie(
        ADMIN_COOKIE,
        token,
        max_age=SESSION_TTL_MS // 1000,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return resp


@app.post("/admin/logout")
def admin_logout() -> JSONResponse:
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie(ADMIN_COOKIE, path="/")
    return resp


@app.get("/admin/me")
def admin_me(ctx: dict = Depends(require_admin)) -> JSONResponse:
    return JSONResponse(content={"email": ctx["admin"]["email"], "tenant": ctx["tenant"]["slug"]})


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
