"""Metrics collector para queries DATASUS."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MethodMetrics:
    query_count: int = 0
    total_time_ms: float = 0.0


@dataclass
class DatasusMetrics:
    total_queries: int = 0
    total_time_ms: float = 0.0
    by_method: dict[str, MethodMetrics] = field(default_factory=dict)
    row_cache_hits: int = 0
    row_cache_misses: int = 0


class MetricsCollector:
    """Coleta metricas de performance das queries DATASUS."""

    def __init__(self) -> None:
        self._total_queries = 0
        self._total_time_ms = 0.0
        self._by_method: dict[str, MethodMetrics] = {}
        self._row_cache_hits = 0
        self._row_cache_misses = 0

    def record(self, method: str, time_ms: float) -> None:
        self._total_queries += 1
        self._total_time_ms += time_ms
        m = self._by_method.get(method)
        if m:
            m.query_count += 1
            m.total_time_ms += time_ms
        else:
            self._by_method[method] = MethodMetrics(1, time_ms)

    def record_row_cache(self, hits: int, misses: int) -> None:
        self._row_cache_hits += hits
        self._row_cache_misses += misses

    @property
    def snapshot(self) -> DatasusMetrics:
        return DatasusMetrics(
            total_queries=self._total_queries,
            total_time_ms=self._total_time_ms,
            by_method={
                k: MethodMetrics(v.query_count, v.total_time_ms)
                for k, v in self._by_method.items()
            },
            row_cache_hits=self._row_cache_hits,
            row_cache_misses=self._row_cache_misses,
        )
