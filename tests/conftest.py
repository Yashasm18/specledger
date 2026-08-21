"""Test-suite configuration.

The application refuses to start without a PostgreSQL DATABASE_URL, because
a deployment that silently falls back to ephemeral storage loses every
review decision on restart. Tests are the one legitimate exception: they
must run in milliseconds, on any machine, without provisioning a database.

That exception is opted into explicitly here rather than being inferred
from an absent DATABASE_URL — which is exactly the ambiguity the strict
check exists to remove.

Set before any application module is imported, since the store is chosen at
import time.
"""

from __future__ import annotations

import os

os.environ.setdefault("SPECLEDGER_ALLOW_EPHEMERAL_STORE", "1")
