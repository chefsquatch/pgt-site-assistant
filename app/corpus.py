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


def _dir(profile: str) -> Path:
    """Corpus folder per assistant profile: 'site' (PGT services) or 'tinker' (Tinker help)."""
    if profile == "tinker":
        return config.TINKER_CORPUS_DIR
    return config.CORPUS_DIR


@lru_cache(maxsize=4)
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
