"""Loads the services corpus — PGT's PUBLIC-FACING services story, and nothing
else. Every substantive answer the assistant gives is grounded in this text.

The corpus is a folder of Markdown files (corpus/*.md). They are concatenated,
in filename order, into one ground-truth block that is handed to the model as the
ONLY source it may answer PGT questions from. Editing the corpus is how offerings
are updated — no code change required.

IP RAIL: nothing proprietary goes in these files. No Kernel internals, no private
substrate architecture, no canon. Shop window, not workshop.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from . import config


def _read_corpus_files(corpus_dir: Path) -> list[tuple[str, str]]:
    if not corpus_dir.exists():
        return []
    out: list[tuple[str, str]] = []
    for path in sorted(corpus_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            out.append((path.name, text))
    return out


# A tenant slug is lowercase letters, digits and hyphens. Checked before it ever becomes a
# path, so "tenant:../corpus" can never read outside corpus_tenants/.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug or ""))


def tenant_profile(slug: str) -> str:
    return f"tenant:{slug}"


def _dir(profile: str) -> Path:
    """Corpus folder per assistant profile: 'site' (PGT services), 'tinker' (Tinker help),
    or 'tenant:<slug>' (a client business, Brick 4b)."""
    if profile == "tinker":
        return config.TINKER_CORPUS_DIR
    if profile.startswith("tenant:"):
        slug = profile.split(":", 1)[1]
        if not valid_slug(slug):
            raise ValueError(f"invalid tenant slug {slug!r}")
        return config.TENANTS_CORPUS_DIR / slug
    return config.CORPUS_DIR


@lru_cache(maxsize=64)
def load_corpus(profile: str = "site") -> str:
    """Return the whole corpus as one grounding block, section-tagged by file."""
    blocks = []
    for name, text in _read_corpus_files(_dir(profile)):
        blocks.append(f"### SOURCE: {name}\n{text}")
    return "\n\n".join(blocks)


def corpus_sections(profile: str = "site") -> list[str]:
    """Filenames currently in the corpus (for /health and tests)."""
    return [name for name, _ in _read_corpus_files(_dir(profile))]


def is_empty(profile: str = "site") -> bool:
    return load_corpus(profile).strip() == ""
