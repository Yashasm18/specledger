import tempfile
import unittest
import hashlib
from pathlib import Path
from uuid import uuid4

import fitz

from backend.specledger.object_store import LocalObjectStore
from backend.specledger.tasks import TaskQueue
from backend.specledger.worker import DocumentProcessingWorker


class WorkerTests(unittest.TestCase):
    def test_worker_claims_and_extracts_pdf_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf_path = Path(directory) / "source.pdf"
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 72), "Pressure rating: 600 WOG")
            document.save(pdf_path)
            document.close()

            store = LocalObjectStore(Path(directory) / "objects")
            store.put("document-001", pdf_path.read_bytes())
            try:
                queue = TaskQueue("postgresql://specledger:specledger_dev_only@localhost:5432/specledger")
            except (RuntimeError, Exception) as e:
                raise unittest.SkipTest(f"PostgreSQL task queue not available: {e}")

            organization_id = "worker-test-" + uuid4().hex
            content = pdf_path.read_bytes()
            queue.register_document(organization_id, "document-001", "source.pdf", "application/pdf", "document-001", hashlib.sha256(content).hexdigest(), len(content), "valve")
            task = queue.enqueue(organization_id, "pdf_extract-verify", "document-001")
            # The worker's production task type is pdf_extract; use that type
            # and a unique organization so this integration test cannot claim
            # another test task left in the shared development database.
            queue.complete(organization_id, task.task_id)
            task = queue.enqueue(organization_id, "pdf_extract", "document-001")
            worker = DocumentProcessingWorker(queue, store, "worker-test")
            result = worker.run_once(organization_id)
            self.assertIsNotNone(result)
            assert result is not None
            self.assertIn("Pressure rating", result.pages[0].text)
            artifact = queue.latest_artifact(organization_id, "document-001")
            self.assertIsNotNone(artifact)
            assert artifact is not None
            self.assertTrue(store.exists(artifact["object_key"]))
            import json
            saved = json.loads(store.get(artifact["object_key"]))
            self.assertEqual(saved["facts"][0]["name"], "pressure_rating")
            self.assertEqual(saved["facts"][0]["page"], 1)
            self.assertEqual(saved["facts"][0]["normalized_value"], "600")
            self.assertEqual(saved["facts"][0]["normalized_unit"], "wog")
            issue_codes = {issue["code"] for issue in saved["validation"]["issues"]}
            self.assertIn("MISSING_REQUIRED", issue_codes)
            self.assertEqual(saved["catalogue_schema"]["id"], "industrial.valve")
            self.assertEqual(artifact["review_state"], "pending_review")
            queue.set_artifact_review_state(organization_id, artifact["artifact_id"], "approved", "reviewer-1", "Evidence checked")
            queue.set_artifact_review_state(organization_id, artifact["artifact_id"], "approved", "reviewer-1", "Retry")
            self.assertEqual(queue.latest_artifact(organization_id, "document-001")["review_state"], "approved")
            self.assertEqual(len(queue.artifact_audit(organization_id, artifact["artifact_id"])), 1)
            self.assertEqual(queue.artifact_audit(organization_id, artifact["artifact_id"])[0]["payload"]["review_state"], "approved")
            queue.close()


if __name__ == "__main__":
    unittest.main()


class ExtractionStoreAgnosticTests(unittest.TestCase):
    """Extraction must use only the object store's interface.

    _extract() wrote the fetched bytes to a temporary file inside
    `object_store.root` before opening it. That attribute exists only on the
    local development store, so against the deployed Supabase-backed store
    every extraction raised AttributeError — an uploaded PDF was accepted,
    queued, and then silently never processed.

    The only other worker test needs PostgreSQL, so it is skipped in CI, and
    it passes a LocalObjectStore either way. Neither would have caught this.
    """

    class _StoreWithoutRoot:
        """A store exposing get() and nothing else, like the remote one."""

        def __init__(self, content: bytes) -> None:
            self._content = content

        def get(self, object_key: str) -> bytes:  # noqa: ARG002
            return self._content

    def _one_page_pdf(self, text: str) -> bytes:
        document = fitz.open()
        document.new_page().insert_text((72, 72), text)
        data = document.tobytes()
        document.close()
        return data

    def test_extract_works_without_a_filesystem_backed_store(self) -> None:
        from backend.specledger.tasks import ProcessingTask

        pdf = self._one_page_pdf("Pressure rating: 600 WOG")
        worker = DocumentProcessingWorker(
            queue=None,  # type: ignore[arg-type]
            object_store=self._StoreWithoutRoot(pdf),
        )
        task = ProcessingTask(
            task_id="t-1", organization_id="default", task_type="pdf_extract",
            state="processing", attempts=1, document_id="doc-1", error_message=None,
        )
        extracted = worker._extract(task)  # pylint: disable=protected-access

        self.assertEqual(extracted.document_id, "doc-1")
        self.assertEqual(len(extracted.pages), 1)
        self.assertIn("600 WOG", extracted.pages[0].text)
