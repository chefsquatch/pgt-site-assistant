"""Seed (or reset) PGT's admin account — Brick 3. Idempotent.

The first admin's credentials are the founder's to choose, so they are NOT baked into
code. Set them in the environment and run this once against the store (Neon in prod):

    ADMIN_EMAIL=you@example.com ADMIN_INITIAL_PASSWORD='a-strong-password' python -m scripts.seed_admin

Re-running with a new ADMIN_INITIAL_PASSWORD resets the password (upsert on the unique
(tenant, email)). The password is hashed with scrypt (app/auth.py) before it ever
touches the database — the plaintext is never stored and never printed back.

Deliberately separate from the request path, like scripts/init_db.py.
"""

from __future__ import annotations

import os
import sys

from app import admins, db
from app.auth import hash_password
from app.db_schema import PGT_TENANT_SLUG


def main() -> int:
    email = (os.getenv("ADMIN_EMAIL") or "").strip()
    password = os.getenv("ADMIN_INITIAL_PASSWORD") or ""
    if not email or not password:
        print(
            "[seed_admin] ADMIN_EMAIL and ADMIN_INITIAL_PASSWORD must both be set.\n"
            "  ADMIN_EMAIL=you@example.com ADMIN_INITIAL_PASSWORD='...' python -m scripts.seed_admin",
            file=sys.stderr,
        )
        return 2

    conn = db.connect()
    conn.autocommit = True
    try:
        tenant = db.resolve_tenant(conn, PGT_TENANT_SLUG)
        if tenant is None:
            print(
                "[seed_admin] PGT tenant zero not found — run `python -m scripts.init_db` first.",
                file=sys.stderr,
            )
            return 1
        admin_id = admins.upsert_admin(
            conn, tenant["id"], email=email, password_hash=hash_password(password)
        )
        who = admins.normalize_email(email)
        print(f"[seed_admin] admin ready: id={admin_id} email={who} tenant={PGT_TENANT_SLUG}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
