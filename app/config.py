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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# The founder's real inbox — the single handoff target. Public-facing already.
FOUNDER_EMAIL = os.getenv("FOUNDER_EMAIL", "lesfleming@precisionguessworktech.com")

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
