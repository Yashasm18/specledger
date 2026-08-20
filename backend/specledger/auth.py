"""Shared API-key gate for write endpoints.

Read-only GET endpoints stay open so hackathon judges can browse data without
credentials; anything that creates, mutates, or triggers heavy work requires
the key. If SPECLEDGER_API_KEY isn't set (local dev, tests), the check is a
no-op so existing workflows keep working unauthenticated.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException

API_KEY = os.getenv("SPECLEDGER_API_KEY")


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key header")
