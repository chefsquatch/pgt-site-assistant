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
# Tinker in-app help (2026-10-24): the same grounded-or-honest assistant, answering from
# Tinker's how-to docs instead of PGT's services story. Separate folder, separate prompt.
TINKER_CORPUS_DIR = ROOT_DIR / "corpus_tinker"
# Client tenants (Brick 4b, 2026-10-25): one folder per tenant slug, corpus_tenants/<slug>/*.md,
# holding that business's own public facts (services, hours, prices, area). Same grounding rail
# as the site and Tinker profiles; editing the folder is how a client's assistant is updated.
TENANTS_CORPUS_DIR = ROOT_DIR / "corpus_tenants"
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

# Client lead alerts go out from the verified PGT domain so they can reach any client inbox
# (Resend's shared onboarding sender can only deliver to the Resend account's own address).
CLIENT_LEAD_FROM = os.getenv("CLIENT_LEAD_FROM", "PGT Leads <leads@precisionguessworktech.com>").strip()
# The key for the Resend account where that domain IS verified (2026-10-25 live proof: the
# site's RESEND_API_KEY belongs to an account without it, so client alerts 403'd). Separate
# slot so the contact form keeps its own key; falls back to RESEND_API_KEY when unset.
CLIENT_RESEND_API_KEY = os.getenv("CLIENT_RESEND_API_KEY", "").strip() or RESEND_API_KEY

# Public client chat (/t/<slug>/chat) is open to any origin, so it is rate limited per IP.
CLIENT_CHAT_PER_HOUR = int(os.getenv("CLIENT_CHAT_PER_HOUR", "40"))
CLIENT_CHAT_PER_MIN = int(os.getenv("CLIENT_CHAT_PER_MIN", "8"))

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
