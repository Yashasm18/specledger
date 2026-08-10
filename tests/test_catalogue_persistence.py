"""Tests for the catalogue persistence layer."""

import unittest

from backend.specledger.catalogue_persistence import (
    InMemoryCatalogueStore, CatalogueStore,
)


class InMemoryCatalogueStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = InMemoryCatalogueStore()

    def test_save_and_get_batch(self) -> None:
        batch_data = {
            "batch_id": "b-1",
            "organization_id": "default",
            "source_name": "valves.csv",
            "columns": ["Manufacturer", "Part Number"],
            "row_count": 1,
            "verified_rate": 1.0,
            "rows": [
                {
                    "row_number": 1,
                    "fields": [
                        {"column": "Manufacturer", "raw_value": "Parker", "canonical_value": "Parker Hannifin"}
                    ],
                }
            ],
        }
        self.store.save_batch(batch_data)
        retrieved = self.store.get_batch("default", "b-1")
        assert retrieved is not None
        assert retrieved["source_name"] == "valves.csv"
        assert retrieved["row_count"] == 1

    def test_get_nonexistent_batch_returns_none(self) -> None:
        assert self.store.get_batch("default", "nonexistent") is None

    def test_get_batch_row(self) -> None:
        batch_data = {
            "batch_id": "b-2",
            "organization_id": "default",
            "source_name": "items.csv",
            "columns": ["Manufacturer"],
            "row_count": 2,
            "verified_rate": 0.5,
            "rows": [
                {"row_number": 1, "status": "verified"},
                {"row_number": 2, "status": "review_required"},
            ],
        }
        self.store.save_batch(batch_data)
        row = self.store.get_batch_row("default", "b-2", 2)
        assert row is not None
        assert row["status"] == "review_required"

    def test_list_batches(self) -> None:
        self.store.save_batch({
            "batch_id": "b-10", "organization_id": "org1",
            "source_name": "f1.csv", "row_count": 5, "verified_rate": 0.8,
        })
        self.store.save_batch({
            "batch_id": "b-11", "organization_id": "org1",
            "source_name": "f2.csv", "row_count": 10, "verified_rate": 0.9,
        })
        self.store.save_batch({
            "batch_id": "b-12", "organization_id": "other_org",
            "source_name": "f3.csv", "row_count": 1, "verified_rate": 1.0,
        })

        batches = self.store.list_batches("org1")
        assert len(batches) == 2
        batch_ids = {b["batch_id"] for b in batches}
        assert batch_ids == {"b-10", "b-11"}

    def test_update_row_review_state(self) -> None:
        self.store.save_batch({
            "batch_id": "b-20",
            "organization_id": "default",
            "source_name": "f.csv",
            "row_count": 1,
            "verified_rate": 0.0,
            "rows": [{"row_number": 1, "review_state": "pending_review"}],
        })

        updated = self.store.update_row_review_state(
            "default", "b-20", 1, "approved", reviewed_by="admin@example.com"
        )
        assert updated is not None
        assert updated["review_state"] == "approved"
        assert updated["reviewed_by"] == "admin@example.com"


if __name__ == "__main__":
    unittest.main()
