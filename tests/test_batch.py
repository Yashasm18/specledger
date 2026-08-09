import unittest

from backend.specledger.batch import BatchImportService, BatchJobRepository, JobState
from backend.specledger.repository import ProductRepository
from backend.specledger.sample_data import sample_product, valve_version
from backend.specledger.models import Product


class BatchImportTests(unittest.TestCase):
    def test_batch_completes_and_reports_progress(self) -> None:
        products = ProductRepository()
        jobs = BatchJobRepository()
        service = BatchImportService(products, jobs, chunk_size=2)
        first = sample_product()
        second = Product("valve-002", "VALVE-002", "Second Valve", "industrial_valve", (valve_version("v1", 500, "second.pdf", "valve-002"),))
        result = service.run("job-001", "org-001", [first, second])
        self.assertEqual(result.state, JobState.COMPLETED)
        self.assertEqual(result.total_items, 2)
        self.assertEqual(result.completed_items, 2)
        self.assertEqual(result.progress, 1.0)
        self.assertIsNotNone(products.get_product("valve-002"))
        products.close()
        jobs.close()

    def test_duplicate_import_is_idempotent(self) -> None:
        products = ProductRepository()
        jobs = BatchJobRepository()
        service = BatchImportService(products, jobs)
        product = sample_product()
        first = service.run("job-001", "org-001", [product])
        second = service.run("job-002", "org-001", [product])
        self.assertEqual(first.completed_items, 1)
        self.assertEqual(second.completed_items, 1)
        products.close()
        jobs.close()


if __name__ == "__main__":
    unittest.main()
