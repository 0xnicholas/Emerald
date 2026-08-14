"""Custom Prometheus business metrics for Emerald.

All metrics are registered on the default global registry so that
prometheus-fastapi-instrumentator's /v1/metrics endpoint collects them
automatically.
"""

from __future__ import annotations

import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Counters
# ---------------------------------------------------------------------------
memory_add_total = Counter(
    "emerald_memory_add_total",
    "Total number of memories added.",
    ["memory_type"],
)

profile_cache_hit_total = Counter(
    "emerald_profile_cache_hit_total",
    "Total number of profile cache hits.",
    ["backend"],
)

profile_cache_miss_total = Counter(
    "emerald_profile_cache_miss_total",
    "Total number of profile cache misses.",
)

pipeline_jobs_total = Counter(
    "emerald_pipeline_jobs_total",
    "Total number of pipeline jobs processed.",
    ["status"],
)

relationship_infer_total = Counter(
    "emerald_relationship_infer_total",
    "Total number of relationships inferred.",
    ["rel_type"],
)

mentions_extracted_total = Counter(
    "emerald_mentions_extracted_total",
    "Total number of named-entity mentions extracted during ingestion (B3 NER).",
)

multihop_paths_returned_total = Counter(
    "emerald_multihop_paths_returned_total",
    "Total number of multihop results (paths) returned across searches (B4).",
)

forget_communities_total = Counter(
    "emerald_forget_communities_total",
    "Community forgetting decisions (B5): per-community actions.",
    ["action"],
)

consolidate_duplicates_total = Counter(
    "emerald_consolidate_duplicates_total",
    "Duplicate consolidation decisions (B6): per-pair actions.",
    ["action"],
)

# ---------------------------------------------------------------------------
# Histograms
# ---------------------------------------------------------------------------
search_latency_seconds = Histogram(
    "emerald_search_latency_seconds",
    "Search latency in seconds.",
    ["search_mode"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

profile_compute_latency_seconds = Histogram(
    "emerald_profile_compute_latency_seconds",
    "Profile compute latency in seconds.",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

memory_add_latency_seconds = Histogram(
    "emerald_memory_add_latency_seconds",
    "Memory add latency in seconds.",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

search_hops = Histogram(
    "emerald_search_hops",
    "Graph traversal depth requested per multihop search query (B4).",
    # Depth is clamped to [0, 4] (MAX_DEPTH); 0 is never observed — the
    # histogram is touched only when the walk is opted in.
    buckets=[1, 2, 3, 4],
)


@contextmanager
def timed(histogram: Histogram, **labels: Any) -> Generator[None, None, None]:
    """Context manager that observes elapsed time into a Histogram.

    Usage::

        with timed(search_latency_seconds, search_mode=mode.value):
            results = await self._search(...)
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        if labels:
            histogram.labels(**labels).observe(elapsed)
        else:
            histogram.observe(elapsed)
