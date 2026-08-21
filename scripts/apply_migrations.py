#!/usr/bin/env python3
"""Apply pending SQL migrations, in order, exactly once.

Until now migrations were applied by hand, which is how the LLM columns in
008 came to be missing in production while the code that writes them was
already deployed — the write silently dropped them.

Records what it applied in `schema_migrations`, so re-running is a no-op and
a fresh database and a long-lived one converge on the same schema.

Usage:
    railway run python scripts/apply_migrations.py            # against the deployed DB
    DATABASE_URL=postgresql://... python scripts/apply_migrations.py
    ... --dry-run                                             # show pending only

`railway run` injects the service's own DATABASE_URL, so the credential
never needs to be copied anywhere.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


def _fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List pending migrations without applying them.",
    )
    args = parser.parse_args()

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        _fail("DATABASE_URL is not set. Use `railway run python scripts/apply_migrations.py`.")

    try:
        import psycopg
    except ImportError:
        _fail("psycopg is not installed. Run: pip install -r requirements.txt")

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        _fail(f"no .sql files found in {MIGRATIONS_DIR}")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(_TRACKING_TABLE)
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        conn.commit()

        pending = [f for f in files if f.name not in applied]

        # A database predating the tracking table already has the early
        # migrations applied; every migration is written to be re-runnable
        # (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS), so
        # replaying them to backfill the record is safe.
        print(f"{len(applied)} already applied, {len(pending)} pending\n")
        for f in pending:
            print(f"  pending: {f.name}")

        if not pending:
            print("nothing to do.")
            return
        if args.dry_run:
            print("\ndry run — nothing applied.")
            return

        print()
        for f in pending:
            sql = f.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (filename) VALUES (%s) "
                        "ON CONFLICT (filename) DO NOTHING",
                        (f.name,),
                    )
                conn.commit()
                print(f"  applied {f.name}")
            except Exception as exc:
                conn.rollback()
                _fail(f"{f.name} failed, rolled back: {exc}")

    print(f"\ndone — {len(pending)} migration(s) applied.")


if __name__ == "__main__":
    main()
