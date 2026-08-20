"""Shared rate limiter for the heaviest, most abusable public endpoints."""

from __future__ import annotations

import os
import sys

from slowapi import Limiter
from slowapi.util import get_remote_address

# Repeated calls to the same endpoint within one test run share a key
# ("testclient"), so real limits would make the suite flaky. Disable
# enforcement under pytest; production keeps it on. This module loads at
# collection time (before pytest sets PYTEST_CURRENT_TEST), so detect via
# "pytest" already being imported rather than that env var.
_disabled = "pytest" in sys.modules or os.getenv("SPECLEDGER_DISABLE_RATE_LIMIT") == "1"

limiter = Limiter(key_func=get_remote_address, enabled=not _disabled)
