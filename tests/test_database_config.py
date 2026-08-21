"""PostgreSQL is required. These pin that rule so it cannot quietly erode.

The failure mode being prevented is specific: a deployment missing
DATABASE_URL used to start happily on ephemeral storage, look healthy, and
lose every review decision on restart. Refusing to start is the point.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.specledger.database import (
    ALLOW_EPHEMERAL_ENV,
    DatabaseNotConfiguredError,
    ephemeral_storage_allowed,
    resolve_database_url,
)


class DatabaseRequirementTests(unittest.TestCase):
    def test_returns_the_configured_url(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "postgresql://db/x"}, clear=False):
            self.assertEqual(resolve_database_url(), "postgresql://db/x")

    def test_a_configured_url_wins_over_the_opt_in(self) -> None:
        # Postgres is preferred whenever it is available, even in tests.
        with patch.dict(
            "os.environ",
            {"DATABASE_URL": "postgresql://db/x", ALLOW_EPHEMERAL_ENV: "1"},
            clear=False,
        ):
            self.assertEqual(resolve_database_url(), "postgresql://db/x")

    def test_refuses_to_start_without_a_database(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "", ALLOW_EPHEMERAL_ENV: ""}, clear=False):
            with self.assertRaises(DatabaseNotConfiguredError):
                resolve_database_url()

    def test_whitespace_only_url_counts_as_unset(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "   ", ALLOW_EPHEMERAL_ENV: ""}, clear=False):
            with self.assertRaises(DatabaseNotConfiguredError):
                resolve_database_url()

    def test_the_error_says_how_to_fix_it(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "", ALLOW_EPHEMERAL_ENV: ""}, clear=False):
            try:
                resolve_database_url()
                self.fail("expected DatabaseNotConfiguredError")
            except DatabaseNotConfiguredError as exc:
                message = str(exc)
                self.assertIn("docker compose up", message)
                self.assertIn("apply_migrations", message)
                self.assertIn(ALLOW_EPHEMERAL_ENV, message)

    def test_ephemeral_storage_must_be_opted_into_explicitly(self) -> None:
        # An absent DATABASE_URL must never be read as permission to run
        # without one — that inference is the whole bug being prevented.
        with patch.dict("os.environ", {ALLOW_EPHEMERAL_ENV: ""}, clear=False):
            self.assertFalse(ephemeral_storage_allowed())

        for value in ("1", "true", "TRUE", "yes"):
            with patch.dict("os.environ", {ALLOW_EPHEMERAL_ENV: value}, clear=False):
                self.assertTrue(ephemeral_storage_allowed(), f"{value!r} should enable it")

        for value in ("0", "false", "no", "maybe"):
            with patch.dict("os.environ", {ALLOW_EPHEMERAL_ENV: value}, clear=False):
                self.assertFalse(ephemeral_storage_allowed(), f"{value!r} should not enable it")

    def test_opt_in_returns_none_rather_than_raising(self) -> None:
        with patch.dict("os.environ", {"DATABASE_URL": "", ALLOW_EPHEMERAL_ENV: "1"}, clear=False):
            self.assertIsNone(resolve_database_url())


if __name__ == "__main__":
    unittest.main()
