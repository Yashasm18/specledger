"""Tests for the human review routing and audit trail."""

import unittest

from backend.specledger.catalogue_ingestion import normalize_rows
from backend.specledger.enrichment import enrich_batch, EnrichedBatch
from backend.specledger.reference_data import ReferenceStore
from backend.specledger.validation_engine import validate_batch
from backend.specledger.human_review import (
    ReviewQueue, ReviewState, ReviewableRow, AuditEvent,
    route_batch_for_review, approve_row, reject_row, correct_row,
    ReviewError,
)


class ReviewHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def _make_enriched_and_validated(self, rows: list[dict]) -> tuple:
        batch = normalize_rows("test.csv", rows)
        enriched = enrich_batch(batch, self.store)
        validation = validate_batch(enriched)
        return enriched, validation


class ReviewRoutingTests(ReviewHelpers):
    def test_verified_rows_auto_approved(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        row = queue.get_row("batch-1", 2)
        assert row is not None
        assert row.state == ReviewState.AUTO_APPROVED

    def test_unmatched_rows_sent_to_review(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "TotallyUnknownCorp", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        row = queue.get_row("batch-1", 2)
        assert row is not None
        assert row.state == ReviewState.PENDING_REVIEW

    def test_missing_required_sends_to_review(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "--", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        row = queue.get_row("batch-1", 2)
        assert row is not None
        assert row.state == ReviewState.PENDING_REVIEW

    def test_audit_trail_created_on_routing(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        row = queue.get_row("batch-1", 2)
        assert row is not None
        assert len(row.audit_trail) == 1
        event = row.audit_trail[0]
        assert event.previous_state == "new"
        assert event.reviewer is None  # system action

    def test_mixed_batch_routing(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "UnknownCo", "Part Number": "V-2"},
            {"Manufacturer": "Emerson", "Part Number": "V-3"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        assert queue.total_count == 3
        # At least one auto-approved, at least one pending
        assert queue.approved_count >= 1
        assert queue.pending_count >= 1


class ReviewQueueTests(ReviewHelpers):
    def test_get_pending_returns_priority_order(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "UnknownCo1", "Part Number": "V-1"},
            {"Manufacturer": "--", "Part Number": "V-2"},  # Missing = higher priority
            {"Manufacturer": "UnknownCo2", "Part Number": "V-3"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        pending = queue.get_pending("batch-1")
        if len(pending) >= 2:
            # Row with missing manufacturer should have higher priority (lower number)
            priorities = [r.priority for r in pending]
            assert priorities == sorted(priorities)  # ascending order

    def test_get_pending_with_limit(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "UnknownCo1", "Part Number": "V-1"},
            {"Manufacturer": "UnknownCo2", "Part Number": "V-2"},
            {"Manufacturer": "UnknownCo3", "Part Number": "V-3"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        pending = queue.get_pending("batch-1", limit=1)
        assert len(pending) <= 1

    def test_get_batch_summary(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "UnknownCo", "Part Number": "V-2"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        summary = queue.get_batch_summary("batch-1")
        assert summary["batch_id"] == "batch-1"
        assert summary["total_rows"] == 2

    def test_queue_summary(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        summary = queue.summary()
        assert "total" in summary
        assert "pending_review" in summary
        assert "approved" in summary

    def test_get_nonexistent_row_returns_none(self) -> None:
        queue = ReviewQueue()
        assert queue.get_row("batch-x", 999) is None


class ReviewActionTests(ReviewHelpers):
    def _setup_pending_row(self) -> tuple[ReviewQueue, str]:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "UnknownCo", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        return queue, "batch-1"

    def test_approve_row(self) -> None:
        queue, batch_id = self._setup_pending_row()
        row = approve_row(queue, batch_id, 2, reviewer="reviewer@example.com", comment="Looks correct")
        assert row.state == ReviewState.APPROVED
        assert len(row.audit_trail) == 2  # routing + approve
        last_event = row.audit_trail[-1]
        assert last_event.action == "approve"
        assert last_event.reviewer == "reviewer@example.com"
        assert last_event.comment == "Looks correct"

    def test_reject_row(self) -> None:
        queue, batch_id = self._setup_pending_row()
        row = reject_row(queue, batch_id, 2, reviewer="reviewer@example.com", comment="Incorrect data")
        assert row.state == ReviewState.REJECTED
        assert len(row.audit_trail) == 2
        assert row.audit_trail[-1].action == "reject"

    def test_correct_row(self) -> None:
        queue, batch_id = self._setup_pending_row()
        corrections = {"manufacturer": "Parker Hannifin"}
        row = correct_row(queue, batch_id, 2, reviewer="reviewer@example.com",
                          corrections=corrections, comment="Fixed manufacturer")
        assert row.state == ReviewState.CORRECTED
        assert len(row.audit_trail) == 2
        last_event = row.audit_trail[-1]
        assert last_event.action == "correct"
        assert last_event.corrections == {"manufacturer": "Parker Hannifin"}

    def test_cannot_approve_already_approved(self) -> None:
        queue, batch_id = self._setup_pending_row()
        approve_row(queue, batch_id, 2, reviewer="reviewer@example.com")
        with self.assertRaises(ReviewError):
            approve_row(queue, batch_id, 2, reviewer="other@example.com")

    def test_cannot_reject_auto_approved(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        with self.assertRaises(ReviewError):
            reject_row(queue, "batch-1", 2, reviewer="reviewer@example.com")

    def test_cannot_approve_nonexistent_row(self) -> None:
        queue = ReviewQueue()
        with self.assertRaises(ReviewError):
            approve_row(queue, "batch-x", 999, reviewer="reviewer@example.com")

    def test_correct_row_requires_corrections(self) -> None:
        queue, batch_id = self._setup_pending_row()
        with self.assertRaises(ReviewError):
            correct_row(queue, batch_id, 2, reviewer="reviewer@example.com", corrections={})


class ReviewSerializationTests(ReviewHelpers):
    def test_audit_event_to_dict(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        row = queue.get_row("batch-1", 2)
        assert row is not None
        event_dict = row.audit_trail[0].to_dict()
        assert "event_id" in event_dict
        assert "timestamp" in event_dict
        assert "action" in event_dict

    def test_reviewable_row_to_dict(self) -> None:
        enriched, validation = self._make_enriched_and_validated([
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-100"},
        ])
        queue = route_batch_for_review("batch-1", enriched, validation)
        row = queue.get_row("batch-1", 2)
        assert row is not None
        row_dict = row.to_dict()
        assert "state" in row_dict
        assert "priority" in row_dict
        assert "validation" in row_dict
        assert "audit_trail" in row_dict


if __name__ == "__main__":
    unittest.main()
