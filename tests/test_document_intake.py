"""Tests for what intake does with an already-registered document.

Intake deduplicates by content hash. It used to return
``{"state": "already_registered", "task_id": None}`` for any repeat upload,
which meant a document whose extraction had failed could never be
reprocessed: re-uploading the identical file enqueued nothing. Two
documents sat permanently failed in production behind the old
``'SupabaseObjectStore' object has no attribute 'root'`` error with no way
to retry them short of editing the database.

Re-uploading a file is the one gesture a user has to say "try again", so it
has to mean that when — and only when — there is nothing to show for the
first attempt.
"""

import unittest

from backend.specledger.http_api import resolve_repeat_intake


class RepeatIntakeTests(unittest.TestCase):
    def test_reprocesses_when_no_artifact_exists(self) -> None:
        # The first attempt failed, so nothing was ever produced.
        assert resolve_repeat_intake(artifact=None) == "reprocess"

    def test_reprocesses_when_artifact_has_no_facts_and_is_unreviewed(self) -> None:
        # An artifact exists but is empty and nobody has looked at it;
        # a retry costs one worker pass and can only improve on nothing.
        artifact = {"fact_count": 0, "review_state": "pending_review"}
        assert resolve_repeat_intake(artifact=artifact) == "reprocess"

    def test_returns_existing_artifact_when_facts_were_extracted(self) -> None:
        artifact = {"fact_count": 3, "review_state": "pending_review"}
        assert resolve_repeat_intake(artifact=artifact) == "already_extracted"

    def test_does_not_reprocess_a_reviewed_artifact(self) -> None:
        # A human has ruled on this document. Re-running extraction could
        # replace values a reviewer already accepted, so it must not.
        artifact = {"fact_count": 0, "review_state": "approved"}
        assert resolve_repeat_intake(artifact=artifact) == "already_extracted"

    def test_does_not_reprocess_a_rejected_artifact(self) -> None:
        artifact = {"fact_count": 0, "review_state": "rejected"}
        assert resolve_repeat_intake(artifact=artifact) == "already_extracted"


if __name__ == "__main__":
    unittest.main()
