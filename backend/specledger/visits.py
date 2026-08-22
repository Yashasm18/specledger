"""Tell the owner when someone opens the live dashboard.

The dashboard is a static page on GitHub Pages and cannot send mail. It
pings the API on load; the API records the arrival and emails a
notification through Resend.

Two rules shape everything here:

* **It must never affect the visitor.** A missing API key, a refused
  connection or a slow provider all degrade to "recorded, not sent". The
  endpoint answers immediately and the send happens on a background
  thread, so a judge opening the page never waits on an email provider.

* **It must never store an IP address.** A timestamp, the referrer and a
  summarised user agent are enough to know that someone arrived and where
  they came from. Nothing here identifies a person.

The recipient is configuration, not a constant: this repository is public,
and a plaintext address in source is an invitation to scrapers.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

logger = logging.getLogger("specledger")

RESEND_ENDPOINT = "https://api.resend.com/emails"
# Resend's shared sender works with no domain verification, which keeps
# setup to a single environment variable.
DEFAULT_SENDER = "SpecLedger <onboarding@resend.dev>"
APP_URL = "https://yashasm18.github.io/specledger/"


@dataclass(frozen=True)
class Visit:
    """One arrival at the dashboard. Deliberately holds no identifier."""
    referrer: str = ""
    user_agent: str = ""
    path: str = ""
    workspace: str = ""
    at: datetime | None = None


@dataclass(frozen=True)
class Delivery:
    api_key: str
    to: str
    sender: str


def resolve_delivery(env: Mapping[str, str]) -> Delivery | None:
    """Read the mail configuration, or None when it is not set up.

    Absence is a normal state, not an error: the visit is still recorded,
    and the deployment simply does not send mail.
    """
    key = str(env.get("RESEND_API_KEY") or "").strip()
    to = str(env.get("ALERT_EMAIL_TO") or "").strip()
    if not key or not to:
        return None
    sender = str(env.get("ALERT_EMAIL_FROM") or "").strip() or DEFAULT_SENDER
    return Delivery(api_key=key, to=to, sender=sender)


_BROWSERS = (
    ("Edg/", "Edge"), ("OPR/", "Opera"), ("Chrome/", "Chrome"),
    ("Firefox/", "Firefox"), ("Safari/", "Safari"),
)
_PLATFORMS = (
    ("iPhone", "iOS"), ("iPad", "iPadOS"), ("Android", "Android"),
    ("Macintosh", "macOS"), ("Mac OS X", "macOS"), ("Windows", "Windows"),
    ("Linux", "Linux"),
)
_BOT = re.compile(r"bot|crawler|spider|slurp|headless|curl|wget|python-requests", re.I)


def summarise_agent(user_agent: str) -> str:
    """Describe the browser without repeating the raw agent string.

    Crawlers are named as crawlers: bot traffic is the main source of
    noise on a public page, and an alert that looks like a real visitor
    when it is Googlebot is worse than no alert.
    """
    ua = str(user_agent or "").strip()
    if not ua:
        return "unknown browser"
    if _BOT.search(ua):
        name = ua.split("/")[0].split("(")[0].strip() or "crawler"
        return f"{name} (bot)"
    browser = next((label for token, label in _BROWSERS if token in ua), "unknown browser")
    platform = next((label for token, label in _PLATFORMS if token in ua), "")
    return f"{browser} on {platform}" if platform else browser


def build_alert(visit: Visit) -> tuple[str, str]:
    """The subject and plain-text body of the arrival email."""
    when = (visit.at or datetime.now(timezone.utc)).strftime("%d %b %Y, %H:%M UTC")
    browser = summarise_agent(visit.user_agent)
    source = visit.referrer.strip() or "direct — typed, bookmarked or from a link with no referrer"

    subject = f"SpecLedger — someone just opened the live app ({browser})"
    body = (
        "Someone opened the SpecLedger dashboard.\n\n"
        f"  When       {when}\n"
        f"  Came from  {source}\n"
        f"  Browser    {browser}\n"
        f"  Page       {visit.path or APP_URL}\n"
        f"  Workspace  {visit.workspace or 'Unilog CX1 Master'}\n\n"
        f"Open it yourself: {APP_URL}\n\n"
        "No address or identifier is collected for this alert — only the\n"
        "time, the referring link and a summary of the browser.\n"
    )
    return subject, body


def send_alert(visit: Visit, env: Mapping[str, str] | None = None) -> str:
    """Send the arrival email. Returns what happened; never raises.

    The caller is a request handler, so failure here must be invisible to
    the visitor.
    """
    delivery = resolve_delivery(env if env is not None else os.environ)
    if delivery is None:
        return "unconfigured"

    subject, body = build_alert(visit)
    try:
        import requests
        response = requests.post(
            RESEND_ENDPOINT,
            headers={"Authorization": f"Bearer {delivery.api_key}",
                     "Content-Type": "application/json"},
            json={"from": delivery.sender, "to": [delivery.to],
                  "subject": subject, "text": body},
            timeout=8,
        )
        if response.status_code >= 400:
            logger.warning("Visit alert refused by provider: %s", response.status_code)
            return f"failed:{response.status_code}"
        return "sent"
    except Exception as exc:  # pylint: disable=broad-except
        # An email provider being unreachable must not surface to a visitor.
        logger.warning("Visit alert could not be sent: %s", exc)
        return "failed"


def send_alert_in_background(visit: Visit) -> None:
    """Hand the send to a daemon thread so the response returns at once."""
    threading.Thread(target=send_alert, args=(visit,),
                     name="visit-alert", daemon=True).start()
