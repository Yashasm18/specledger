"""Tests for the batch processing infrastructure."""

import unittest

from backend.specledger.catalogue_ingestion import normalize_rows
from backend.specledger.reference_data import ReferenceStore
from backend.specledger.batch_processor import (
    process_batch, BatchStatus, SourceCache, CostTracker,
    ProcessingMetrics, BatchProcessingResult,
)


class SourceCacheTests(unittest.TestCase):
    def test_cache_miss_then_hit(self) -> None:
        from backend.specledger.source_discovery import discover_sources_simulated
        cache = SourceCache()
        assert cache.get("Parker Hannifin", "V-100") is None
        assert cache.misses == 1
        result = discover_sources_simulated("Parker Hannifin", "V-100")
        cache.put("Parker Hannifin", "V-100", result)
        cached = cache.get("Parker Hannifin", "V-100")
        assert cached is not None
        assert cache.hits == 1

    def test_hit_rate(self) -> None:
        from backend.specledger.source_discovery import discover_sources_simulated
        cache = SourceCache()
        result = discover_sources_simulated("Parker Hannifin", "V-100")
        cache.put("Parker Hannifin", "V-100", result)
        cache.get("Parker Hannifin", "V-100")  # hit
        cache.get("Parker Hannifin", "V-100")  # hit
        cache.get("Emerson", "E-200")  # miss
        assert cache.hit_rate > 0.5

    def test_case_insensitive_keys(self) -> None:
        from backend.specledger.source_discovery import discover_sources_simulated
        cache = SourceCache()
        result = discover_sources_simulated("Parker Hannifin", "V-100")
        cache.put("Parker Hannifin", "V-100", result)
        assert cache.get("parker hannifin", "v-100") is not None

    def test_clear_cache(self) -> None:
        from backend.specledger.source_discovery import discover_sources_simulated
        cache = SourceCache()
        cache.put("Parker Hannifin", "V-100", discover_sources_simulated("Parker Hannifin", "V-100"))
        assert cache.size == 1
        cache.clear()
        assert cache.size == 0
        assert cache.hits == 0
        assert cache.misses == 0


class CostTrackerTests(unittest.TestCase):
    def test_record_row_cost(self) -> None:
        tracker = CostTracker()
        estimate = tracker.record_row(source_lookups=1, llm_calls=0)
        assert estimate.total_cost > 0
        assert tracker.total_rows == 1
        assert tracker.total_cost > 0

    def test_average_cost(self) -> None:
        tracker = CostTracker()
        tracker.record_row(source_lookups=1)
        tracker.record_row(source_lookups=1)
        tracker.record_row(source_lookups=0)  # cached
        assert tracker.average_cost_per_row > 0

    def test_monthly_projections(self) -> None:
        tracker = CostTracker()
        tracker.record_row(source_lookups=1)
        assert tracker.projected_monthly_cost_150k > 0
        assert tracker.projected_monthly_cost_750k > tracker.projected_monthly_cost_150k

    def test_cost_summary_serialization(self) -> None:
        tracker = CostTracker()
        tracker.record_row(source_lookups=1)
        summary = tracker.summary()
        assert "total_rows" in summary
        assert "total_cost_usd" in summary
        assert "projected_monthly_150k_usd" in summary
        assert "projected_monthly_750k_usd" in summary


class MetricsTests(unittest.TestCase):
    def test_record_latency(self) -> None:
        metrics = ProcessingMetrics(start_time=1000.0, total_rows=10)
        metrics.record_row_latency(5.0)
        metrics.record_row_latency(10.0)
        metrics.record_row_latency(15.0)
        assert metrics.processed_rows == 3
        assert metrics.p50_latency_ms == 10.0

    def test_failure_rate(self) -> None:
        metrics = ProcessingMetrics(total_rows=10)
        metrics.record_failure()
        metrics.record_failure()
        assert metrics.failure_rate == 0.2
        assert metrics.success_rate == 0.8

    def test_summary_serialization(self) -> None:
        metrics = ProcessingMetrics(start_time=1000.0, total_rows=5)
        metrics.end_time = 1001.0
        metrics.record_row_latency(10.0)
        summary = metrics.summary()
        assert "throughput_rows_per_sec" in summary
        assert "p50_latency_ms" in summary
        assert "failure_rate" in summary

    def test_throughput(self) -> None:
        metrics = ProcessingMetrics(start_time=1000.0, total_rows=100)
        metrics.end_time = 1001.0  # 1 second
        for _ in range(100):
            metrics.record_row_latency(5.0)
        assert metrics.throughput_rows_per_second == 100.0


class BatchProcessingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = ReferenceStore()

    def test_process_small_batch(self) -> None:
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Emerson", "Part Number": "V-2"},
        ])
        result = process_batch(batch, self.store)
        assert result.status == BatchStatus.COMPLETED
        assert result.enriched is not None
        assert result.enriched.row_count == 2
        assert result.validation is not None
        assert result.review_queue is not None

    def test_process_batch_produces_metrics(self) -> None:
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
        ])
        result = process_batch(batch, self.store)
        assert result.metrics.total_rows == 1
        assert result.metrics.processed_rows == 1
        assert result.metrics.elapsed_seconds > 0

    def test_process_batch_deterministic_path_is_free(self) -> None:
        # The default (non-live_fetch) path makes zero external API calls —
        # simulated source discovery and enrichment are both local, so the
        # real cost is genuinely $0, not an estimated placeholder.
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Emerson", "Part Number": "V-2"},
        ])
        result = process_batch(batch, self.store)
        assert result.cost.total_rows == 2
        assert result.cost.total_cost == 0
        assert result.cost.projected_monthly_cost_750k == 0

    def test_process_batch_discovers_sources(self) -> None:
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
        ])
        result = process_batch(batch, self.store)
        assert len(result.sources) >= 1

    def test_cache_shared_across_duplicates(self) -> None:
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},  # duplicate
        ])
        result = process_batch(batch, self.store)
        assert result.source_cache.hits >= 1

    def test_progress_callback_called(self) -> None:
        progress_log: list[tuple[int, int]] = []
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "Emerson", "Part Number": "V-2"},
        ])
        process_batch(batch, self.store, progress_callback=lambda p, t: progress_log.append((p, t)))
        assert len(progress_log) == 2
        assert progress_log[-1] == (2, 2)

    def test_result_summary(self) -> None:
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
        ])
        result = process_batch(batch, self.store)
        summary = result.summary()
        assert "batch_id" in summary
        assert "status" in summary
        assert "metrics" in summary
        assert "cost" in summary
        assert "cache" in summary
        assert "validation" in summary
        assert "review" in summary
        assert "enrichment" in summary

    def test_process_with_unknown_manufacturers(self) -> None:
        batch = normalize_rows("test.csv", [
            {"Manufacturer": "Parker Hannifin", "Part Number": "V-1"},
            {"Manufacturer": "UnknownCo", "Part Number": "V-2"},
        ])
        result = process_batch(batch, self.store)
        assert result.status == BatchStatus.COMPLETED
        # Unknown manufacturer should still be processed
        assert result.review_queue is not None
        assert result.review_queue.pending_count >= 1


if __name__ == "__main__":
    unittest.main()
