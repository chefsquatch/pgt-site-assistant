"""Apply the engine's schema + RLS wall, and seed PGT as tenant zero. Idempotent.

Run once against a fresh Neon database (and re-runnable safely thereafter):

    python -m scripts.init_db

Migrations + RLS are applied here, deliberately separate from the request path (the
running app never mutates its own schema) — the same split Tinker makes between
migrate-prod and the serving handles.
"""

from __future__ import annotations

import sys

from app import db, db_schema

# PGT is tenant zero: the first tenant on the engine, and the one whose own site the
# engine runs on before it is ever sold. The identity lives in db_schema so the seed
# here and the runtime capture seam (app/leads.py) resolve the exact same slug.
PGT_SLUG = db_schema.PGT_TENANT_SLUG
PGT_NAME = db_schema.PGT_TENANT_NAME


def init(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(db_schema.SCHEMA_SQL)
        for stmt in db_schema.rls_policy_statements():
            cur.execute(stmt)
    conn.commit()

    # Seed PGT tenant zero. on conflict do nothing -> idempotent re-runs.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenant (slug, name) VALUES (%s, %s) "
            "ON CONFLICT (slug) DO NOTHING",
            (PGT_SLUG, PGT_NAME),
        )
    conn.commit()


def main() -> int:
    conn = db.connect()
    try:
        init(conn)
        tenant = db.resolve_tenant(conn, PGT_SLUG)
        print(
            "[init_db] schema + RLS wall applied; "
            f"PGT tenant zero present: {tenant}"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
