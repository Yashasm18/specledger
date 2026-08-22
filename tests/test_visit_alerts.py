"""Arrival alerts: someone opened the live app.

The dashboard is a static page on GitHub Pages, so it cannot send mail
itself. It pings the API on load, the API records the arrival and emails a
notification.

Two rules shape this. It must never affect the page: a missing API key, a
refused SMTP connection or a slow provider all degrade to "recorded, not
sent", and never to an error the visitor can see. And it must never store
an IP address — a timestamp, the referrer and a truncated user agent are
enough to know someone arrived and where they came from.
"""

import unittest

from backend.specledger.visits import (
    Visit, build_alert, resolve_delivery, summarise_agent,
)


def _visit(**kw) -> Visit:
    base = dict(referrer="https://github.com/Yashasm18/specledger",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/140.0",
                path="/specledger/", workspace="default")
    base.update(kw)
    return Visit(**base)


class DeliveryConfigTests(unittest.TestCase):
    """Nothing is sent unless both a key and a recipient are configured."""

    def test_unconfigured_is_not_an_error(self) -> None:
        assert resolve_delivery({}) is None

    def test_key_without_recipient_does_not_send(self) -> None:
        assert resolve_delivery({"RESEND_API_KEY": "re_x"}) is None

    def test_recipient_without_key_does_not_send(self) -> None:
        assert resolve_delivery({"ALERT_EMAIL_TO": "someone@example.com"}) is None

    def test_fully_configured_resolves(self) -> None:
        d = resolve_delivery({"RESEND_API_KEY": "re_x", "ALERT_EMAIL_TO": "someone@example.com"})
        assert d is not None
        assert d.to == "someone@example.com"
        assert d.api_key == "re_x"

    def test_sender_defaults_but_can_be_overridden(self) -> None:
        base = {"RESEND_API_KEY": "re_x", "ALERT_EMAIL_TO": "a@b.com"}
        assert "@" in resolve_delivery(base).sender
        custom = resolve_delivery({**base, "ALERT_EMAIL_FROM": "alerts@specledger.dev"})
        assert custom.sender == "alerts@specledger.dev"

    def test_blank_values_count_as_unconfigured(self) -> None:
        assert resolve_delivery({"RESEND_API_KEY": "  ", "ALERT_EMAIL_TO": "a@b.com"}) is None


class AlertContentTests(unittest.TestCase):
    def test_subject_says_someone_opened_the_app(self) -> None:
        subject, _ = build_alert(_visit())
        assert "SpecLedger" in subject

    def test_body_names_the_referrer(self) -> None:
        _, body = build_alert(_visit(referrer="https://devfolio.co/projects/specledger"))
        assert "devfolio.co" in body

    def test_direct_visit_says_so_rather_than_showing_blank(self) -> None:
        _, body = build_alert(_visit(referrer=""))
        assert "direct" in body.casefold()

    def test_body_reports_the_browser_not_the_raw_agent_string(self) -> None:
        _, body = build_alert(_visit())
        assert "Chrome" in body
        assert "Mozilla/5.0 (Macintosh" not in body

    def test_no_ip_address_is_ever_included(self) -> None:
        _, body = build_alert(_visit())
        assert "ip" not in body.casefold().split()


class AgentSummaryTests(unittest.TestCase):
    def test_chrome_on_mac(self) -> None:
        assert summarise_agent(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/140.0") == "Chrome on macOS"

    def test_safari_on_iphone(self) -> None:
        assert summarise_agent(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Version/17.0 Safari/605.1") == "Safari on iOS"

    def test_unknown_agent_is_reported_as_unknown(self) -> None:
        assert summarise_agent("") == "unknown browser"

    def test_a_crawler_is_named_as_one(self) -> None:
        # Bot traffic is the main source of noise on a public page; the alert
        # should say so rather than looking like a real visitor.
        assert "bot" in summarise_agent("Googlebot/2.1 (+http://www.google.com/bot.html)").casefold()


if __name__ == "__main__":
    unittest.main()
