"""Tests for the optional LLM enrichment tier.

Every test here mocks the HTTP layer — the suite must never make a real
billed API call, and must pass with no GEMINI_API_KEY configured.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.specledger.llm_enricher import (
    ALLOWED_CLASSPATHS,
    GENERIC_CLASSPATH,
    LLMUsage,
    enrich_unresolved,
    is_llm_configured,
    needs_llm,
)


def _fake_response(status_code=200, classifications=None, usage=None):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code
            self.text = "error body"

        def json(self):
            return {
                "candidates": [
                    {"content": {"parts": [
                        {"text": json.dumps({"classifications": classifications or []})}
                    ]}}
                ],
                "usageMetadata": usage or {
                    "promptTokenCount": 100, "candidatesTokenCount": 20,
                },
            }
    return FakeResponse()


class NeedsLlmTests(unittest.TestCase):
    def test_generic_bucket_is_unresolved(self) -> None:
        self.assertTrue(needs_llm(GENERIC_CLASSPATH))

    def test_missing_classpath_is_unresolved(self) -> None:
        self.assertTrue(needs_llm(None))
        self.assertTrue(needs_llm(""))

    def test_specific_classpath_is_resolved(self) -> None:
        self.assertFalse(
            needs_llm("Industrial Supplies > Abrasives > Sanding Belts & Discs")
        )


class DisabledTierTests(unittest.TestCase):
    def test_no_api_key_means_disabled(self) -> None:
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}, clear=False):
            self.assertFalse(is_llm_configured())

    def test_returns_empty_without_a_key_and_makes_no_request(self) -> None:
        with patch("backend.specledger.llm_enricher.requests.post") as post:
            result = enrich_unresolved(
                [{"id": 1, "description": "ball valve"}], api_key=None,
            )
        post.assert_not_called()
        self.assertEqual(result.suggestions, {})
        self.assertEqual(result.usage.calls_made, 0)

    def test_empty_input_makes_no_request(self) -> None:
        with patch("backend.specledger.llm_enricher.requests.post") as post:
            enrich_unresolved([], api_key="k")
        post.assert_not_called()


class SuggestionParsingTests(unittest.TestCase):
    def test_parses_a_valid_classification(self) -> None:
        target = "Plumbing & Industrial Piping > Industrial Valves & Fittings > Ball Valves"
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(classifications=[
                {"id": 7, "classpath": target, "confidence": 0.91, "reasoning": "says ball valve"},
            ]),
        ):
            result = enrich_unresolved([{"id": 7, "description": "2in ball valve"}], api_key="k")

        self.assertIn(7, result.suggestions)
        self.assertEqual(result.suggestions[7].classpath, target)
        self.assertAlmostEqual(result.suggestions[7].confidence, 0.91)
        # Suggestions must be self-identifying as AI-derived and versioned.
        payload = result.suggestions[7].to_dict()
        self.assertEqual(payload["status"], "ai_inferred")
        self.assertTrue(payload["prompt_version"])

    def test_discards_a_classpath_outside_the_controlled_vocabulary(self) -> None:
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(classifications=[
                {"id": 1, "classpath": "Invented > Category", "confidence": 0.99},
            ]),
        ):
            result = enrich_unresolved([{"id": 1, "description": "x"}], api_key="k")
        self.assertEqual(result.suggestions, {})

    def test_declining_to_classify_yields_no_suggestion(self) -> None:
        # Returning the generic bucket is the deterministic answer we already
        # have, so it must not be recorded as an AI contribution.
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(classifications=[
                {"id": 1, "classpath": GENERIC_CLASSPATH, "confidence": 0.4},
            ]),
        ):
            result = enrich_unresolved([{"id": 1, "description": "x"}], api_key="k")
        self.assertEqual(result.suggestions, {})
        self.assertEqual(result.usage.rows_resolved, 0)

    def test_clamps_confidence_into_range(self) -> None:
        target = ALLOWED_CLASSPATHS[0]
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(classifications=[
                {"id": 1, "classpath": target, "confidence": 4.2},
                {"id": 2, "classpath": target, "confidence": -1.0},
            ]),
        ):
            result = enrich_unresolved(
                [{"id": 1, "description": "a"}, {"id": 2, "description": "b"}], api_key="k",
            )
        self.assertEqual(result.suggestions[1].confidence, 1.0)
        self.assertEqual(result.suggestions[2].confidence, 0.0)

    def test_skips_malformed_entries_without_failing_the_batch(self) -> None:
        target = ALLOWED_CLASSPATHS[0]
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(classifications=[
                {"id": "not-an-int", "classpath": target, "confidence": 0.9},
                {"classpath": target},
                {"id": 3, "classpath": target, "confidence": 0.8},
            ]),
        ):
            result = enrich_unresolved([{"id": 3, "description": "a"}], api_key="k")
        self.assertEqual(list(result.suggestions), [3])


class FailureHandlingTests(unittest.TestCase):
    def test_http_error_degrades_to_no_suggestions(self) -> None:
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(status_code=429),
        ):
            result = enrich_unresolved([{"id": 1, "description": "x"}], api_key="k")
        self.assertEqual(result.suggestions, {})
        self.assertTrue(result.usage.errors)

    def test_network_exception_does_not_propagate(self) -> None:
        import requests as _requests
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            side_effect=_requests.RequestException("connection reset"),
        ):
            result = enrich_unresolved([{"id": 1, "description": "x"}], api_key="k")
        self.assertEqual(result.suggestions, {})
        self.assertIn("request failed", result.usage.errors[0])


class BatchingAndCostTests(unittest.TestCase):
    def test_batches_rows_to_bound_the_number_of_calls(self) -> None:
        # 60 rows at a batch size of 25 must cost 3 calls, not 60.
        items = [{"id": i, "description": "x"} for i in range(60)]
        with patch(
            "backend.specledger.llm_enricher.requests.post",
            return_value=_fake_response(classifications=[]),
        ) as post:
            result = enrich_unresolved(items, api_key="k", batch_size=25)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(result.usage.calls_made, 3)
        self.assertEqual(result.usage.rows_submitted, 60)

    def test_cost_is_derived_from_measured_tokens_and_configured_rates(self) -> None:
        usage = LLMUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
        with patch.dict(
            "os.environ",
            {"SPECLEDGER_LLM_INPUT_RATE": "0.10", "SPECLEDGER_LLM_OUTPUT_RATE": "0.40"},
            clear=False,
        ):
            self.assertAlmostEqual(usage.cost_usd, 0.50)

    def test_usage_payload_labels_what_is_measured_versus_configured(self) -> None:
        payload = LLMUsage(prompt_tokens=10, completion_tokens=5, rows_submitted=2).to_dict()
        self.assertTrue(payload["token_counts_measured"])
        self.assertTrue(payload["rate_is_configured_not_measured"])
        self.assertEqual(payload["total_tokens"], 15)


if __name__ == "__main__":
    unittest.main()
