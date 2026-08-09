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
            queue = TaskQueue("postgresql://specledger:specledger_dev_only@localhost:5432/specledger")
            organization_id = "worker-test-" + uuid4().hex
            content = pdf_path.read_bytes()
            queue.register_document(organization_id, "document-001", "source.pdf", "application/pdf", "document-001", hashlib.sha256(content).hexdigest(), len(content))
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
            self.assertEqual(saved["catalogue_schema"]["id"], "industrial.generic")
            self.assertEqual(artifact["review_state"], "pending_review")
            queue.set_artifact_review_state(organization_id, artifact["artifact_id"], "approved", "reviewer-1", "Evidence checked")
            queue.set_artifact_review_state(organization_id, artifact["artifact_id"], "approved", "reviewer-1", "Retry")
            self.assertEqual(queue.latest_artifact(organization_id, "document-001")["review_state"], "approved")
            self.assertEqual(len(queue.artifact_audit(organization_id, artifact["artifact_id"])), 1)
            self.assertEqual(queue.artifact_audit(organization_id, artifact["artifact_id"])[0]["payload"]["review_state"], "approved")
            queue.close()


if __name__ == "__main__":
    unittest.main()
