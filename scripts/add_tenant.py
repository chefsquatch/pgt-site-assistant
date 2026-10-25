"""Add (or update) a client business as a tenant — Brick 4b. Idempotent.

    TENANT_SLUG=terry-allen TENANT_NAME="Terry Allen Plumbing & Heating" \
    TENANT_NOTIFY_EMAIL=owner@example.com python -m scripts.add_tenant

Then give the business its knowledge folder (corpus_tenants/<slug>/*.md), its owner login
(TENANT_SLUG=<slug> ADMIN_EMAIL=... ADMIN_INITIAL_PASSWORD=... python -m scripts.seed_admin),
and put the widget tag on its site. Re-running updates the name and alert email.

The tenant table is the directory (not tenant-scoped), so this writes it directly, the same
way init_db seeds PGT tenant zero. Deliberately separate from the request path.
"""

from __future__ import annotations

import os
import sys

from app import corpus, db


def main() -> int:
    slug = (os.getenv("TENANT_SLUG") or "").strip().lower()
    name = (os.getenv("TENANT_NAME") or "").strip()
    notify = (os.getenv("TENANT_NOTIFY_EMAIL") or "").strip() or None
    if not corpus.valid_slug(slug) or not name:
        print(
            "[add_tenant] TENANT_SLUG (lowercase letters, digits, hyphens) and TENANT_NAME are required.",
            file=sys.stderr,
        )
        return 2

    conn = db.connect()
    conn.autocommit = True
    try:
        conn.execute(
            "INSERT INTO tenant (slug, name, notify_email) VALUES (%s, %s, %s) "
            "ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, notify_email = EXCLUDED.notify_email",
            (slug, name, notify),
        )
        tenant = db.resolve_tenant(conn, slug)
        has_corpus = not corpus.is_empty(corpus.tenant_profile(slug))
        print(f"[add_tenant] tenant ready: slug={tenant['slug']} name={tenant['name']} "
              f"alerts={'set' if tenant['notify_email'] else 'PGT inbox only'} "
              f"knowledge={'loaded' if has_corpus else 'MISSING: add corpus_tenants/' + slug + '/'}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
