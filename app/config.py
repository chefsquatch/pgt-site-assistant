"""Configuration, loaded from the environment.

The API key lives ONLY in the environment (a gitignored .env locally, the deploy
platform's dashboard in production). It is never hard-coded and never committed.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # dotenv is a convenience in dev; prod sets real env vars
    pass

ROOT_DIR = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT_DIR / "corpus"
STATIC_DIR = ROOT_DIR / "static"

# .strip() is load-bearing: a key pasted into a deploy dashboard often carries a
# trailing newline or space. httpx refuses to send an x-api-key header containing
# whitespace and the SDK surfaces that as a bare "Connection error" (the request
# never leaves) — indistinguishable from a network failure unless you strip here.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5").strip()

# The founder's PUBLIC address — shown to visitors ("reach Les at ..."). Never
# changes based on the email plumbing below.
FOUNDER_EMAIL = os.getenv("FOUNDER_EMAIL", "lesfleming@precisionguessworktech.com")

# Where the contact form actually DELIVERS leads. Decoupled from the public
# address on purpose: with Resend's shared onboarding sender (no verified domain
# yet), email can only be delivered to the Resend account's own address. Set
# LEAD_INBOX to whatever email you signed up to Resend with. Defaults to the
# public address (correct once precisionguessworktech.com is a verified sender).
LEAD_INBOX = os.getenv("LEAD_INBOX", "").strip() or FOUNDER_EMAIL

# Contact form -> transactional email via Resend. The key is required to boot
# (see main.py startup): we refuse to accept leads we can't deliver. Stripped for
# the same pasted-whitespace reason as the Anthropic key.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
# Resend's shared onboarding sender works immediately; verifying
# precisionguessworktech.com as the sender domain is a later optional polish.
RESEND_FROM = os.getenv("RESEND_FROM", "PGT Site <onboarding@resend.dev>").strip()

# Cap on conversation length sent to the model (turns kept from the tail).
MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "24"))

# Origins allowed to call the API (the live site + local dev). Comma-separated.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "ALLOWED_ORIGINS",
        "https://precisionguessworktech.com,https://www.precisionguessworktech.com,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]
