"""BRICK 3 — auth primitives: scrypt password hashing + HMAC session tokens.

Pure-function tests (no database). Mirrors Tinker's password + session guarantees.
"""

from __future__ import annotations

from app.auth import (
    create_session_token,
    hash_password,
    verify_password,
    verify_session_token,
)

SECRET = "test-secret"


# --- password (scrypt) -----------------------------------------------------------

def test_hash_is_self_describing_and_salted():
    h = hash_password("hunter2")
    assert h.startswith("scrypt$16384$8$1$")
    assert len(h.split("$")) == 6
    # Same password hashed twice differs (random per-hash salt).
    assert hash_password("hunter2") != h


def test_correct_password_verifies():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_wrong_password_rejected():
    h = hash_password("correct horse battery staple")
    assert verify_password("Correct Horse Battery Staple", h) is False
    assert verify_password("", h) is False


def test_malformed_stored_hash_denies_not_raises():
    for bad in ["", "not-a-hash", "scrypt$16384$8$1$deadbeef", "bcrypt$x$y", "scrypt$x$y$z$q$w"]:
        assert verify_password("anything", bad) is False


def test_tampered_hash_rejected():
    h = hash_password("pw")
    parts = h.split("$")
    parts[-1] = ("0" if parts[-1][0] != "0" else "1") + parts[-1][1:]  # flip first hex char
    assert verify_password("pw", "$".join(parts)) is False


# --- session (HMAC-signed token) -------------------------------------------------

def test_session_roundtrip():
    tok = create_session_token("tid", "aid", secret=SECRET)
    s = verify_session_token(tok, secret=SECRET)
    assert s is not None
    assert s.tenant_id == "tid" and s.admin_id == "aid"


def test_wrong_secret_rejected():
    tok = create_session_token("tid", "aid", secret=SECRET)
    assert verify_session_token(tok, secret="other-secret") is None


def test_expired_token_rejected():
    # Minted to expire in the past.
    tok = create_session_token("tid", "aid", now_ms=1_000, ttl_ms=1, secret=SECRET)
    assert verify_session_token(tok, now_ms=1_000_000, secret=SECRET) is None
    # ...but valid before expiry.
    assert verify_session_token(tok, now_ms=1_000, secret=SECRET) is not None


def test_tampered_payload_rejected():
    tok = create_session_token("tid", "aid", secret=SECRET)
    payload, sig = tok.split(".")
    # Flip a character in the payload; the signature no longer matches.
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B") + "." + sig
    assert verify_session_token(tampered, secret=SECRET) is None


def test_malformed_token_rejected():
    for bad in ["", ".", "nodot", "a.", ".b", "a.b.c.d"]:
        assert verify_session_token(bad, secret=SECRET) is None
