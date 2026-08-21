"""Single chokepoint for deciding where SpecLedger stores data.

PostgreSQL is the system of record. It is not one option among several: the
review queue, audit trail and approval state are the product, and they have
to be durable, concurrent and queryable. Nothing else here is a substitute.

Historically each call site did its own ``if DATABASE_URL else <fallback>``,
so a missing variable silently downgraded the whole service to ephemeral
storage — a deployment could look healthy while writing to memory that
vanishes on restart. Worse, the fallbacks did not behave identically to
Postgres, which is how several real bugs stayed hidden in local runs and
only appeared in production.

So the rule is now stated once, here, and it is strict:

    Postgres, or refuse to start.

The only exception is an *explicit* opt-in, ``SPECLEDGER_ALLOW_EPHEMERAL_STORE=1``,
which exists so the test suite can run in milliseconds without a database.
It must be set deliberately — an absent DATABASE_URL never implies it.
"""

from __future__ import annotations

import os

ALLOW_EPHEMERAL_ENV = "SPECLEDGER_ALLOW_EPHEMERAL_STORE"


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when no DATABASE_URL is set and ephemeral storage is not allowed."""


_MESSAGE = """\
DATABASE_URL is not set.

SpecLedger stores catalogue batches, review decisions and audit history in
PostgreSQL. It will not start without one, because falling back to ephemeral
storage would silently lose every approval on restart.

To run locally:

    docker compose up -d
    export DATABASE_URL=postgresql://specledger:specledger_dev_only@localhost:5432/specledger
    python scripts/apply_migrations.py

To run the test suite without a database (tests only — never a deployment):

    export {allow}=1
"""


def ephemeral_storage_allowed() -> bool:
    """True only when ephemeral storage has been explicitly opted into."""
    return os.getenv(ALLOW_EPHEMERAL_ENV, "").strip().lower() in {"1", "true", "yes"}


def resolve_database_url() -> str | None:
    """Return the configured DATABASE_URL.

    Returns None only when ephemeral storage is explicitly allowed; otherwise
    raises rather than letting the service run without a system of record.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    if ephemeral_storage_allowed():
        return None
    raise DatabaseNotConfiguredError(_MESSAGE.format(allow=ALLOW_EPHEMERAL_ENV))
