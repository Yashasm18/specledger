import tempfile
import unittest
from pathlib import Path

from backend.specledger.api import SpecLedgerService
from backend.specledger.models import Product
from backend.specledger.repository import ProductRepository
from backend.specledger.sample_data import sample_product, valve_version


class RepositoryTests(unittest.TestCase):
    def test_product_and_evidence_survive_database_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = ProductRepository(Path(directory) / "specledger.db")
            original = sample_product()
            repository.save_product(original)
            repository.close()

            reopened = ProductRepository(Path(directory) / "specledger.db")
            loaded = reopened.get_product("valve-001")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.latest_version().attribute_map()["pressure_rating"].value, 600)
            self.assertEqual(
                loaded.latest_version().attribute_map()["pressure_rating"].evidence[0].source_name,
                "valve-datasheet-v1.pdf",
            )
            reopened.close()

    def test_service_detects_change_after_second_version_is_saved(self) -> None:
        repository = ProductRepository()
        service = SpecLedgerService(repository)
        first = sample_product()
        second = Product(
            first.product_id,
            first.sku,
            first.name,
            first.category,
            first.versions + (valve_version("v2", 500, "valve-datasheet-v2.pdf"),),
        )
        service.create_or_update_product(first)
        service.create_or_update_product(second)
        changes = service.compare_latest_versions("valve-001")
        self.assertEqual([change["attribute"] for change in changes], ["pressure_rating"])
        repository.close()


if __name__ == "__main__":
    unittest.main()

