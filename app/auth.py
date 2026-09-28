"""Admin auth — Brick 3: scrypt password hashing + HMAC-signed session cookie.

Faithful Python port of Tinker's proven mechanism (src/auth/password.ts + session.ts).
Both halves use ONLY the standard library (hashlib.scrypt, hmac, secrets) — no new
dependency, no native build, clean on Render/Neon, matching the engine's lean posture.

  * PASSWORD (scrypt): an admin signs in with a real password, so it is stored as a
    SALTED, slow-KDF hash and verified by re-derivation — never looked up by equality,
    never reversible. The stored string is self-describing, `scrypt$N$r$p$salt$hash`,
    so a future cost bump re-hashes on next login without breaking stored hashes.

  * SESSION (HMAC): admins stay signed in via a self-contained, HMAC-signed token in an
    HttpOnly cookie — `payload.signature`, payload = base64url(JSON {tenant_id, admin_id,
    exp}), signature = HMAC-SHA256(secret, payload). No server-side session table to
    sweep; tampering invalidates the signature; `exp` bounds the lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

# --- scrypt cost parameters (port of Tinker's). N=16384 → 128*N*r ≈ 16 MB, a
# deliberate interactive-login cost. maxmem is set generously above that so OpenSSL
# never rejects the derivation for its default memory ceiling.
_N = 16384
_R = 8
_P = 1
_KEY_LEN = 64
_SALT_BYTES = 16
_MAXMEM = 64 * 1024 * 1024  # 64 MB — comfortably above 128*N*r


def hash_password(password: str) -> str:
    """Hash a password for storage. Random per-hash salt → equal passwords differ."""
    salt = secrets.token_bytes(_SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_LEN, maxmem=_MAXMEM
    )
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored `scrypt$...` string.

    Re-derives with the stored salt + parameters and compares in constant time. Returns
    False (never raises) on a malformed/unknown stored value, so a corrupt row denies
    access rather than crashing.
    """
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    _, n_str, r_str, p_str, salt_hex, hash_hex = parts
    try:
        n, r, p = int(n_str), int(r_str), int(p_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    if not salt or not expected:
        return False
    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected), maxmem=_MAXMEM
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)


# --- Session tokens -------------------------------------------------------------------

#: The cookie the signed admin session token rides in.
ADMIN_COOKIE = "pgt_admin"

#: Default session lifetime — a generous shift.
SESSION_TTL_MS = 12 * 60 * 60 * 1000

#: Dev/test-only default. NOT a secret — production MUST supply ADMIN_SESSION_SECRET.
_DEV_SESSION_SECRET = "pgt-engine-dev-session-secret-not-for-production"


def resolve_session_secret() -> str:
    """The HMAC signing secret. Real secret from the env when set; otherwise the dev
    default — EXCEPT on Render (prod), where a missing secret raises rather than silently
    signing with a public default. Rotating it invalidates live sessions (re-login), but
    not stored passwords."""
    from_env = (os.getenv("ADMIN_SESSION_SECRET") or "").strip()
    if from_env:
        return from_env
    if os.getenv("RENDER"):  # Render sets this on every deploy → we are in production
        raise RuntimeError(
            "ADMIN_SESSION_SECRET is not set. It is required in production for admin sessions."
        )
    return _DEV_SESSION_SECRET


@dataclass
class AdminSession:
    tenant_id: str
    admin_id: str
    exp: int  # epoch ms; the token is invalid at or after this instant


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(part: str) -> bytes:
    pad = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + pad)


def _sign(payload_part: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_part.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def create_session_token(
    tenant_id: str,
    admin_id: str,
    *,
    now_ms: int | None = None,
    ttl_ms: int = SESSION_TTL_MS,
    secret: str | None = None,
) -> str:
    """Mint a signed session token for an authenticated admin."""
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    secret = secret if secret is not None else resolve_session_secret()
    body = {"tenant_id": str(tenant_id), "admin_id": str(admin_id), "exp": now + ttl_ms}
    payload_part = _b64url_encode(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    return f"{payload_part}.{_sign(payload_part, secret)}"


def verify_session_token(
    token: str,
    *,
    now_ms: int | None = None,
    secret: str | None = None,
) -> AdminSession | None:
    """Verify a session token. Returns the session IFF the signature matches AND it has
    not expired; None otherwise (bad shape, tampered payload, wrong secret, expired). The
    signature is checked in constant time BEFORE the payload is trusted."""
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    secret = secret if secret is not None else resolve_session_secret()

    dot = token.find(".")
    if dot <= 0 or dot == len(token) - 1:
        return None
    payload_part = token[:dot]
    provided_sig = token[dot + 1 :]

    expected_sig = _sign(payload_part, secret)
    if not hmac.compare_digest(provided_sig, expected_sig):
        return None

    try:
        body = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if (
        not isinstance(body, dict)
        or not isinstance(body.get("tenant_id"), str)
        or not isinstance(body.get("admin_id"), str)
        or not isinstance(body.get("exp"), int)
    ):
        return None
    if body["exp"] <= now:
        return None
    return AdminSession(tenant_id=body["tenant_id"], admin_id=body["admin_id"], exp=body["exp"])
