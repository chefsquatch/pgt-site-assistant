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
import time
from collections import defaultdict, deque
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import availability, config, corpus, db, notify
from .admins import find_admin_by_email, find_admin_by_id
from .assistant import (
    AssistantError,
    ConfigError,
    GenerationError,
    respond,
    respond_client,
    respond_tinker,
)
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
from .leads import capture_lead, list_leads

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


# Client chat (/t/<slug>/...) is embedded on each client's own website, so it answers any
# origin. No credentials ever ride on it (no cookies, allow_credentials stays False), which is
# what makes "*" safe here. Every other route keeps the allow-list above. Registered after the
# CORS middleware, so it is the outer layer and answers /t/ preflights before the allow-list.
@app.middleware("http")
async def _client_cors(request: Request, call_next):
    if not request.url.path.startswith("/t/"):
        return await call_next(request)
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
    }
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=headers)
    resp = await call_next(request)
    resp.headers.update(headers)
    return resp


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
            "Something went wrong on my end, and I'd rather tell you than guess. You can "
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
        "tinker_help_sections": corpus.corpus_sections("tinker"),
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


def _tinker_fallback(message: str) -> dict:
    return {
        "error": message,
        "reply": (
            "Help is having trouble right now, so I won't guess. Click \"Email PGT support\" "
            "below and PGT will get back to you."
        ),
        "needs_human": True,
    }


@app.post("/tinker/help")
def tinker_help(req: ChatRequest) -> JSONResponse:
    """Tinker in-app help. Called server-to-server by the Tinker app (which owns the admin's
    session and sends any escalation email itself), so it needs no CORS and stores nothing."""
    history = [{"role": t.role, "content": t.content} for t in req.history]
    try:
        result = respond_tinker(history)
    except ConfigError as exc:
        return JSONResponse(status_code=503, content=_tinker_fallback(str(exc)))
    except GenerationError as exc:
        return JSONResponse(status_code=502, content=_tinker_fallback(str(exc)))
    except AssistantError as exc:
        return JSONResponse(status_code=400, content=_tinker_fallback(str(exc)))
    return JSONResponse(
        content={
            "reply": result.reply,
            "in_corpus": result.in_corpus,
            "needs_human": result.needs_human,
            "issue_summary": result.issue_summary,
        }
    )


# --- Client tenants (Brick 4b) -----------------------------------------------------------
# A client business is a tenant. Its customers chat at /t/<slug>/chat from the widget on the
# business's own site; a captured lead is stored under THAT tenant (the capture seam's
# per-slug resolution) and emailed to its owner. Rate limited per IP (ported from the
# vertical-demos guard), since the route is public and every call costs a model request.

_client_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def _client_rate_limited(ip: str) -> bool:
    now = time.time()
    dq = _client_hits[ip]
    while dq and dq[0] < now - 3600:
        dq.popleft()
    if len(dq) >= config.CLIENT_CHAT_PER_HOUR:
        return True
    if sum(1 for t in dq if t > now - 60) >= config.CLIENT_CHAT_PER_MIN:
        return True
    dq.append(now)
    return False


class ClientChatRequest(BaseModel):
    history: list[Turn]
    # The widget sets this once it has shown a lead, so one conversation stores one lead.
    lead_captured: bool = False


def _client_fallback(message: str) -> dict:
    return {
        "error": message,
        "reply": "Sorry, I'm having trouble right now. Please call or try again in a minute.",
    }


@app.post("/t/{slug}/chat")
def client_chat(slug: str, req: ClientChatRequest, request: Request) -> JSONResponse:
    if not corpus.valid_slug(slug):
        return JSONResponse(status_code=404, content=_client_fallback("Unknown business."))
    if _client_rate_limited(_client_ip(request)):
        return JSONResponse(status_code=429, content=_client_fallback("Too many messages, slow down a moment."))
    try:
        conn = _open_store()
    except Exception:
        return JSONResponse(status_code=503, content=_client_fallback("The store is unavailable."))
    try:
        tenant = db.resolve_tenant(conn, slug)
    finally:
        conn.close()
    if tenant is None:
        return JSONResponse(status_code=404, content=_client_fallback("Unknown business."))

    history = [{"role": t.role, "content": t.content} for t in req.history]
    try:
        result = respond_client(history, business=tenant["name"], slug=slug)
    except ConfigError as exc:
        return JSONResponse(status_code=503, content=_client_fallback(str(exc)))
    except GenerationError as exc:
        return JSONResponse(status_code=502, content=_client_fallback(str(exc)))
    except AssistantError as exc:
        return JSONResponse(status_code=400, content=_client_fallback(str(exc)))

    lead = result.lead if not req.lead_captured else None
    if lead:
        summary = lead["summary"] or ""
        capture_lead(
            problem_summary=("URGENT: " + summary) if lead["urgent"] else summary,
            name=lead["name"],
            email=lead["email"],
            phone=lead["phone"],
            source="assistant",
            tenant_slug=slug,
        )
        notify.email_lead(tenant, lead, history + [{"role": "assistant", "content": result.reply}])

    return JSONResponse(content={"reply": result.reply, "in_corpus": result.in_corpus, "lead": lead})


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
                    "Sorry, I couldn't send that just now. You can email Les "
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
    # Which business's admin is signing in (Brick 4b). Email is unique only WITHIN a tenant,
    # so the login names its workspace; PGT tenant zero when omitted.
    workspace: str = PGT_TENANT_SLUG


def _open_store() -> db.psycopg.Connection:
    """Open an autocommit connection for an auth operation (same contract as the lead
    seam: autocommit so each with_tenant is its own committed transaction)."""
    conn = db.connect()
    conn.autocommit = True
    return conn


def require_admin(request: Request) -> dict:
    """FastAPI dependency: admit only a request carrying a valid session cookie, and scope
    it to the ONE tenant that session was signed for. The tenant comes from the HMAC-signed
    session (it cannot be forged or edited), every route then reads only ctx["tenant"]["id"]
    (F6 filters), and the admin must still exist inside that tenant. Since Brick 4b the
    engine serves client tenants too, so the wall is "a session sees only its own tenant",
    not "only PGT". Raises 401 otherwise, 503 if the store/secret is unavailable."""
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
        tenant = db.get_tenant_by_id(conn, session.tenant_id)
        # The session-layer wall: the session's own tenant, or nothing.
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
        workspace = req.workspace.strip().lower()
        tenant = db.resolve_tenant(conn, workspace) if corpus.valid_slug(workspace) else None
        if tenant is None:
            # Same answer as a wrong password: never reveal which workspaces exist.
            return JSONResponse(status_code=401, content={"ok": False, "error": "Invalid email or password."})
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


@app.get("/admin/leads")
def admin_leads(ctx: dict = Depends(require_admin)) -> JSONResponse:
    """The signed-in tenant's captured leads (Brick 4). require_admin has already
    enforced auth + the session-layer wall; list_leads filters tenant_id (F6)."""
    try:
        conn = _open_store()
    except Exception:
        raise HTTPException(status_code=503, detail="The store is unavailable.")
    try:
        leads = list_leads(conn, ctx["tenant"]["id"])
    finally:
        conn.close()
    return JSONResponse(content={"leads": leads, "count": len(leads)})


# --- Availability (Brick 5) — the admin edits the schedule; it lives as data (F2). ----
# Every route is behind require_admin (auth + session-layer wall) and every store call
# filters tenant_id in SQL (F6). Bad input -> 400 with the reason, never a stack trace.


class TimezoneRequest(BaseModel):
    timezone: str


class WindowRequest(BaseModel):
    weekday: int
    start: str
    end: str
    label: str | None = None


class BlockRequest(BaseModel):
    starts_at: str  # "YYYY-MM-DDTHH:MM", wall time in the tenant's timezone
    ends_at: str
    reason: str | None = None


def _with_store(fn):
    """Open an autocommit store conn, run fn(conn), close. Maps bad input to 400 and an
    unreachable store to 503."""
    try:
        conn = _open_store()
    except Exception:
        raise HTTPException(status_code=503, detail="The store is unavailable.")
    try:
        return fn(conn)
    except availability.AvailabilityError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        conn.close()


def _availability_view(conn, tenant_id) -> dict:
    tz = availability.get_timezone(conn, tenant_id)
    blocks = availability.list_blocks(conn, tenant_id)
    return {
        "timezone": tz,
        "windows": availability.list_windows(conn, tenant_id),
        "blocks": [
            # Rendered in the TENANT's zone (the DB hands back its own session zone).
            {
                **b,
                "starts_at": b["starts_at"].astimezone(ZoneInfo(tz)).isoformat(),
                "ends_at": b["ends_at"].astimezone(ZoneInfo(tz)).isoformat(),
            }
            for b in blocks
        ],
    }


@app.get("/admin/availability")
def admin_availability(ctx: dict = Depends(require_admin)) -> JSONResponse:
    return JSONResponse(content=_with_store(lambda c: _availability_view(c, ctx["tenant"]["id"])))


@app.put("/admin/availability/timezone")
def admin_set_timezone(req: TimezoneRequest, ctx: dict = Depends(require_admin)) -> JSONResponse:
    tz = _with_store(lambda c: availability.set_timezone(c, ctx["tenant"]["id"], req.timezone))
    return JSONResponse(content={"ok": True, "timezone": tz})


@app.post("/admin/availability/windows")
def admin_add_window(req: WindowRequest, ctx: dict = Depends(require_admin)) -> JSONResponse:
    wid = _with_store(
        lambda c: availability.add_window(
            c, ctx["tenant"]["id"], weekday=req.weekday, start=req.start, end=req.end, label=req.label
        )
    )
    return JSONResponse(content={"ok": True, "id": wid})


@app.delete("/admin/availability/windows/{window_id}")
def admin_delete_window(window_id: str, ctx: dict = Depends(require_admin)) -> JSONResponse:
    if not _with_store(lambda c: availability.delete_window(c, ctx["tenant"]["id"], window_id)):
        raise HTTPException(status_code=404, detail="No such window.")
    return JSONResponse(content={"ok": True})


@app.post("/admin/availability/blocks")
def admin_add_block(req: BlockRequest, ctx: dict = Depends(require_admin)) -> JSONResponse:
    def _add(c):
        tid = ctx["tenant"]["id"]
        tz = availability.get_timezone(c, tid)
        return availability.add_block(
            c,
            tid,
            starts_at=availability.parse_local(req.starts_at, tz),
            ends_at=availability.parse_local(req.ends_at, tz),
            reason=req.reason,
        )

    return JSONResponse(content={"ok": True, "id": _with_store(_add)})


@app.delete("/admin/availability/blocks/{block_id}")
def admin_delete_block(block_id: str, ctx: dict = Depends(require_admin)) -> JSONResponse:
    if not _with_store(lambda c: availability.delete_block(c, ctx["tenant"]["id"], block_id)):
        raise HTTPException(status_code=404, detail="No such block.")
    return JSONResponse(content={"ok": True})


@app.get("/admin/availability/open")
def admin_open_windows(days: int = 14, ctx: dict = Depends(require_admin)) -> JSONResponse:
    """Preview of the deterministic read Brick 6 will book against: weekly hours minus
    blocks, in the tenant's timezone."""
    wins = _with_store(lambda c: availability.open_windows(c, ctx["tenant"]["id"], days=days))
    return JSONResponse(
        content={"open": [{"start": w.start.isoformat(), "end": w.end.isoformat()} for w in wins]}
    )


@app.get("/admin")
def admin_page() -> FileResponse:
    """The admin view. The page itself is public HTML/JS; it shows the sign-in form
    until the browser holds a valid session cookie, then calls /admin/leads (which IS
    guarded) to render the leads. No tenant data is embedded in the page."""
    return FileResponse(str(config.STATIC_DIR / "admin.html"))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(config.STATIC_DIR / "index.html"))


@app.get("/client-widget.js")
def client_widget() -> FileResponse:
    """The drop-in chat for a client's own website (Brick 4b): <script src=".../client-widget.js"
    data-tenant="<slug>" ...>. Talks to /t/<slug>/chat."""
    return FileResponse(str(config.STATIC_DIR / "client-widget.js"), media_type="application/javascript")


@app.get("/widget.js")
def widget() -> FileResponse:
    # Served with the same CORS policy; the site embeds it with a <script> tag.
    return FileResponse(
        str(config.STATIC_DIR / "widget.js"),
        media_type="application/javascript",
    )
