"""Human review routing and audit trail for enriched catalogue rows.

This module determines which rows require human review, manages the
review queue, and records a complete audit trail of every review
decision. It works with the validation engine to make routing
decisions.

Review states:
  - pending_review: awaiting human decision
  - auto_approved: passed all validation, no human needed
  - approved: human explicitly approved
  - rejected: human explicitly rejected
  - corrected: human approved with corrections

Every state transition is recorded as an audit event.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from .enrichment import EnrichedBatch, EnrichedRow
from .validation_engine import (
    BatchValidationResult, RowValidationResult,
)


class ReviewState(Enum):
    PENDING_REVIEW = "pending_review"
    AUTO_APPROVED = "auto_approved"
    APPROVED = "approved"
    REJECTED = "rejected"
    CORRECTED = "corrected"


@dataclass(frozen=True)
class AuditEvent:
    """Immutable record of a review action."""
    event_id: str
    row_number: int
    batch_id: str
    timestamp: float
    action: str  # "auto_approve", "submit_for_review", "approve", "reject", "correct"
    previous_state: str
    new_state: str
    reviewer: str | None  # None for system actions
    comment: str | None = None
    corrections: dict | None = None  # field_name → corrected_value

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "row_number": self.row_number,
            "batch_id": self.batch_id,
            "timestamp": self.timestamp,
            "action": self.action,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "reviewer": self.reviewer,
            "comment": self.comment,
            "corrections": self.corrections,
        }


@dataclass
class ReviewableRow:
    """A row with its review state and validation context."""
    row_number: int
    batch_id: str
    state: ReviewState
    validation: RowValidationResult
    priority: float  # lower = higher priority (needs review sooner)
    audit_trail: list[AuditEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "row_number": self.row_number,
            "batch_id": self.batch_id,
            "state": self.state.value,
            "priority": round(self.priority, 4),
            "validation": self.validation.to_dict(),
            "audit_trail": [e.to_dict() for e in self.audit_trail],
        }


@dataclass
class ReviewQueue:
    """In-memory review queue with priority ordering.

    Production implementation would use PostgreSQL with row-level
    locking (SELECT ... FOR UPDATE SKIP LOCKED) to support concurrent
    reviewers.
    """
    _rows: dict[tuple[str, int], ReviewableRow] = field(default_factory=dict)

    @property
    def pending_count(self) -> int:
        return sum(1 for r in self._rows.values() if r.state == ReviewState.PENDING_REVIEW)

    @property
    def approved_count(self) -> int:
        return sum(1 for r in self._rows.values()
                   if r.state in {ReviewState.APPROVED, ReviewState.AUTO_APPROVED, ReviewState.CORRECTED})

    @property
    def rejected_count(self) -> int:
        return sum(1 for r in self._rows.values() if r.state == ReviewState.REJECTED)

    @property
    def total_count(self) -> int:
        return len(self._rows)

    def get_row(self, batch_id: str, row_number: int) -> ReviewableRow | None:
        return self._rows.get((batch_id, row_number))

    def get_pending(self, batch_id: str | None = None, limit: int = 50) -> list[ReviewableRow]:
        """Get pending review rows, sorted by priority (lowest first = most urgent)."""
        pending = [
            r for r in self._rows.values()
            if r.state == ReviewState.PENDING_REVIEW
            and (batch_id is None or r.batch_id == batch_id)
        ]
        pending.sort(key=lambda r: r.priority)
        return pending[:limit]

    def get_audit_events(self, batch_id: str, limit: int = 50) -> list[AuditEvent]:
        """Get a batch's audit events, most recent first, capped at `limit`.

        Use count_audit_events() for the real total — len() of this list is
        the page size, not how many events exist.
        """
        events = self._all_audit_events(batch_id)
        events.sort(key=lambda e: e.timestamp, reverse=True)
        return events[:limit]

    def count_audit_events(self, batch_id: str) -> int:
        """Total number of audit events recorded for a batch, unpaginated."""
        return len(self._all_audit_events(batch_id))

    def _all_audit_events(self, batch_id: str) -> list[AuditEvent]:
        return [
            event
            for row in self._rows.values()
            if row.batch_id == batch_id
            for event in row.audit_trail
        ]

    def get_batch_summary(self, batch_id: str) -> dict:
        """Get review status summary for a batch."""
        batch_rows = [r for r in self._rows.values() if r.batch_id == batch_id]
        return {
            "batch_id": batch_id,
            "total_rows": len(batch_rows),
            "pending_review": sum(1 for r in batch_rows if r.state == ReviewState.PENDING_REVIEW),
            "auto_approved": sum(1 for r in batch_rows if r.state == ReviewState.AUTO_APPROVED),
            "approved": sum(1 for r in batch_rows if r.state == ReviewState.APPROVED),
            "corrected": sum(1 for r in batch_rows if r.state == ReviewState.CORRECTED),
            "rejected": sum(1 for r in batch_rows if r.state == ReviewState.REJECTED),
        }

    def add(self, row: ReviewableRow) -> None:
        self._rows[(row.batch_id, row.row_number)] = row

    def summary(self) -> dict:
        return {
            "total": self.total_count,
            "pending_review": self.pending_count,
            "approved": self.approved_count,
            "rejected": self.rejected_count,
        }


# ---------------------------------------------------------------------------
# Priority scoring
# ---------------------------------------------------------------------------

def _calculate_priority(validation: RowValidationResult, enriched_row: EnrichedRow) -> float:
    """Calculate review priority. Lower score = more urgent.

    Factors:
    - Error count (most important)
    - Warning count
    - Inverse confidence (lower confidence = higher priority)
    - Completeness (less complete = higher priority)
    """
    error_weight = validation.error_count * 10.0
    warning_weight = validation.warning_count * 3.0
    confidence_weight = (1.0 - enriched_row.overall_confidence) * 5.0
    completeness_weight = (1.0 - validation.completeness) * 2.0
    return error_weight + warning_weight + confidence_weight + completeness_weight


# ---------------------------------------------------------------------------
# Review routing
# ---------------------------------------------------------------------------

def route_batch_for_review(
    batch_id: str,
    enriched: EnrichedBatch,
    validation: BatchValidationResult,
    queue: ReviewQueue | None = None,
) -> ReviewQueue:
    """Route enriched rows to auto-approval or human review.

    Creates a ReviewQueue with all rows assigned their initial state.
    """
    if queue is None:
        queue = ReviewQueue()

    now = time.time()
    val_by_row = {v.row_number: v for v in validation.row_results}

    for enriched_row in enriched.rows:
        val_result = val_by_row.get(enriched_row.row_number)
        if val_result is None:
            continue

        priority = _calculate_priority(val_result, enriched_row)

        if val_result.can_auto_approve:
            state = ReviewState.AUTO_APPROVED
            action = "auto_approve"
        else:
            state = ReviewState.PENDING_REVIEW
            action = "submit_for_review"

        event = AuditEvent(
            event_id=str(uuid4()),
            row_number=enriched_row.row_number,
            batch_id=batch_id,
            timestamp=now,
            action=action,
            previous_state="new",
            new_state=state.value,
            reviewer=None,
            comment=f"{'Auto-approved — all validations passed' if val_result.can_auto_approve else f'{val_result.error_count} errors, {val_result.warning_count} warnings'}",
        )

        reviewable = ReviewableRow(
            row_number=enriched_row.row_number,
            batch_id=batch_id,
            state=state,
            validation=val_result,
            priority=priority,
            audit_trail=[event],
        )
        queue.add(reviewable)

    return queue


# ---------------------------------------------------------------------------
# Review actions
# ---------------------------------------------------------------------------

class ReviewError(Exception):
    """Raised when a review action is invalid."""


def approve_row(
    queue: ReviewQueue,
    batch_id: str,
    row_number: int,
    reviewer: str,
    comment: str | None = None,
) -> ReviewableRow:
    """Approve a row that is pending review."""
    row = queue.get_row(batch_id, row_number)
    if row is None:
        raise ReviewError(f"Row {row_number} not found in batch {batch_id}")
    if row.state != ReviewState.PENDING_REVIEW:
        raise ReviewError(f"Cannot approve row in state '{row.state.value}' — must be pending_review")

    event = AuditEvent(
        event_id=str(uuid4()),
        row_number=row_number,
        batch_id=batch_id,
        timestamp=time.time(),
        action="approve",
        previous_state=row.state.value,
        new_state=ReviewState.APPROVED.value,
        reviewer=reviewer,
        comment=comment,
    )
    row.state = ReviewState.APPROVED
    row.audit_trail.append(event)
    return row


def reject_row(
    queue: ReviewQueue,
    batch_id: str,
    row_number: int,
    reviewer: str,
    comment: str | None = None,
) -> ReviewableRow:
    """Reject a row that is pending review."""
    row = queue.get_row(batch_id, row_number)
    if row is None:
        raise ReviewError(f"Row {row_number} not found in batch {batch_id}")
    if row.state != ReviewState.PENDING_REVIEW:
        raise ReviewError(f"Cannot reject row in state '{row.state.value}' — must be pending_review")

    event = AuditEvent(
        event_id=str(uuid4()),
        row_number=row_number,
        batch_id=batch_id,
        timestamp=time.time(),
        action="reject",
        previous_state=row.state.value,
        new_state=ReviewState.REJECTED.value,
        reviewer=reviewer,
        comment=comment,
    )
    row.state = ReviewState.REJECTED
    row.audit_trail.append(event)
    return row


def correct_row(
    queue: ReviewQueue,
    batch_id: str,
    row_number: int,
    reviewer: str,
    corrections: dict[str, str],
    comment: str | None = None,
) -> ReviewableRow:
    """Approve a row with corrections applied."""
    row = queue.get_row(batch_id, row_number)
    if row is None:
        raise ReviewError(f"Row {row_number} not found in batch {batch_id}")
    if row.state != ReviewState.PENDING_REVIEW:
        raise ReviewError(f"Cannot correct row in state '{row.state.value}' — must be pending_review")
    if not corrections:
        raise ReviewError("Corrections dict must not be empty — use approve_row instead")

    event = AuditEvent(
        event_id=str(uuid4()),
        row_number=row_number,
        batch_id=batch_id,
        timestamp=time.time(),
        action="correct",
        previous_state=row.state.value,
        new_state=ReviewState.CORRECTED.value,
        reviewer=reviewer,
        comment=comment,
        corrections=corrections,
    )
    row.state = ReviewState.CORRECTED
    row.audit_trail.append(event)
    return row
