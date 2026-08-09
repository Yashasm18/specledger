import unittest

try:
    from fastapi.testclient import TestClient
    from backend.specledger.http_api import app
except ModuleNotFoundError:
    TestClient = None
    app = None


@unittest.skipIf(TestClient is None, "FastAPI dependencies are not installed")
class HttpApiTests(unittest.TestCase):
    def test_health_endpoint(self) -> None:
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_product_creation_and_retrieval(self) -> None:
        client = TestClient(app)
        product = {
            "product_id": "api-valve-001",
            "sku": "API-VALVE-001",
            "name": "API Test Valve",
            "category": "industrial_valve",
            "versions": [{
                "version_id": "v1",
                "attributes": [{
                    "name": "pressure_rating",
                    "value": 600,
                    "unit": "WOG",
                    "evidence": [{"source_name": "test.pdf", "source_type": "datasheet", "page": 1}]
                }]
            }]
        }
        created = client.post("/products", json=product)
        self.assertEqual(created.status_code, 200)
        retrieved = client.get("/products/api-valve-001")
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json()["sku"], "API-VALVE-001")

