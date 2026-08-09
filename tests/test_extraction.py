import unittest

from backend.specledger.extraction import extract_facts
from backend.specledger.worker import ExtractedDocument, ExtractedPage


class ExtractionTests(unittest.TestCase):
    def test_extracts_only_evidence_backed_facts(self) -> None:
        document = ExtractedDocument("doc-1", (ExtractedPage(2, "Pressure rating: 600 WOG\nMaterial: Brass"),))
        facts = extract_facts(document)
        self.assertEqual([fact.name for fact in facts], ["pressure_rating", "material"])
        self.assertEqual(facts[0].value, 600.0)
        self.assertEqual(facts[0].page, 2)
        self.assertEqual(facts[0].evidence, "Pressure rating: 600 WOG")


if __name__ == "__main__":
    unittest.main()

