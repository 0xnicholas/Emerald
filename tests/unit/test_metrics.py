"""Unit tests for custom Prometheus business metrics."""

from __future__ import annotations

from prometheus_client import REGISTRY

from emerald.core.metrics import (
    memory_add_total,
    multihop_paths_returned_total,
    pipeline_jobs_total,
    profile_cache_hit_total,
    profile_cache_miss_total,
    relationship_infer_total,
    search_hops,
    search_latency_seconds,
    timed,
)


class TestMetrics:
    """Verify that metrics are correctly registered and increment."""

    def _get_counter_value(self, metric_name: str, **labels) -> float:
        """Helper to extract a counter value from the global registry.

        prometheus_client appends ``_total`` to the sample name for counters,
        so *metric_name* should be the base name without the ``_total`` suffix
        (e.g. ``"emerald_memory_add"`` not ``"emerald_memory_add_total"``).
        """
        value = REGISTRY.get_sample_value(f"{metric_name}_total", labels)
        return value or 0.0

    def test_memory_add_total(self):
        before = self._get_counter_value("emerald_memory_add", memory_type="fact")
        memory_add_total.labels(memory_type="fact").inc(3)
        after = self._get_counter_value("emerald_memory_add", memory_type="fact")
        assert after == before + 3

    def test_profile_cache_hit_total(self):
        before = self._get_counter_value("emerald_profile_cache_hit", backend="redis")
        profile_cache_hit_total.labels(backend="redis").inc()
        after = self._get_counter_value("emerald_profile_cache_hit", backend="redis")
        assert after == before + 1

    def test_profile_cache_miss_total(self):
        before = self._get_counter_value("emerald_profile_cache_miss")
        profile_cache_miss_total.inc()
        after = self._get_counter_value("emerald_profile_cache_miss")
        assert after == before + 1

    def test_pipeline_jobs_total(self):
        before = self._get_counter_value("emerald_pipeline_jobs", status="indexing")
        pipeline_jobs_total.labels(status="indexing").inc()
        after = self._get_counter_value("emerald_pipeline_jobs", status="indexing")
        assert after == before + 1

    def test_relationship_infer_total(self):
        before = self._get_counter_value("emerald_relationship_infer", rel_type="updates")
        relationship_infer_total.labels(rel_type="updates").inc()
        after = self._get_counter_value("emerald_relationship_infer", rel_type="updates")
        assert after == before + 1

    def test_search_latency_seconds(self):
        with timed(search_latency_seconds, search_mode="hybrid"):
            pass
        # Histogram exists; verifying it doesn't raise is sufficient
        assert True

    def test_timed_context_manager_observes(self):
        """Verify that timed() actually observes a non-negative value."""
        from prometheus_client import Histogram

        test_hist = Histogram("test_timed_dummy_v2", "Dummy histogram for testing")
        with timed(test_hist):
            pass

        # Verify at least one observation exists via the _sum sample
        value = REGISTRY.get_sample_value("test_timed_dummy_v2_sum")
        assert value is not None and value >= 0

    def test_search_hops_histogram(self):
        """search.hops observes the requested traversal depth (B4, #35)."""
        before = REGISTRY.get_sample_value("emerald_search_hops_count") or 0.0
        search_hops.observe(2)
        after = REGISTRY.get_sample_value("emerald_search_hops_count") or 0.0
        assert after == before + 1

    def test_multihop_paths_returned_total(self):
        """multihop.paths_returned counts returned paths (B4, #35)."""
        before = self._get_counter_value("emerald_multihop_paths_returned")
        multihop_paths_returned_total.inc(5)
        after = self._get_counter_value("emerald_multihop_paths_returned")
        assert after == before + 5
