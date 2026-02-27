"""BaseResource[T] — camada generica de acesso a dados sobre views DuckDB.

Segue o mesmo padrao do processos-core BaseResource<T>:
- list_all(competencias): todos os registros para as competencias
- get_by_id(id, competencias): registro unico por chave primaria
- list_by_ids(ids, competencias): busca em lote por IDs
- search(column, pattern, competencias): busca textual
- Cache integrado com TTL
"""

from __future__ import annotations

import json
import time
from typing import Any, Generic, TypeVar

from .cache import QueryCache
from .connection import DuckDBConnection
from .metrics import MetricsCollector

T = TypeVar("T", bound=dict[str, Any])


def normalize_competencias(
    competencias: str | list[str] | None,
) -> list[str] | None:
    """Normaliza competencias para lista ordenada sem duplicatas."""
    if not competencias:
        return None
    arr = [competencias] if isinstance(competencias, str) else list(competencias)
    return sorted(set(arr))


class BaseResource(Generic[T]):
    """Acesso generico a uma tabela DATASUS registrada como view DuckDB."""

    def __init__(
        self,
        conn: DuckDBConnection,
        table_name: str,
        id_column: str,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._conn = conn
        self._table_name = table_name
        self._id_column = id_column
        self._cache = cache
        self._metrics = metrics

    @property
    def table_name(self) -> str:
        return self._table_name

    def _cached(self, cache_key: str, query_fn: Any) -> Any:
        if self._cache and self._cache.has(cache_key):
            return self._cache.get(cache_key)
        result = query_fn()
        if self._cache:
            self._cache.set(cache_key, result)
        return result

    def _record(self, method: str, start: float) -> None:
        if self._metrics:
            elapsed = (time.monotonic() - start) * 1000
            self._metrics.record(f"{self._table_name}.{method}", elapsed)

    def _comp_clause(
        self, comps: list[str] | None
    ) -> tuple[str, list[Any]]:
        """Retorna clausula WHERE e params para filtro de competencia."""
        if not comps:
            return "", []
        placeholders = ", ".join("?" for _ in comps)
        return f"dt_competencia IN ({placeholders})", list(comps)

    def list_all(
        self, competencias: str | list[str] | None = None
    ) -> list[T]:
        """Lista todos os registros, opcionalmente filtrando por competencia."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.list_all:{json.dumps(comps)}"

        def query() -> list[T]:
            start = time.monotonic()
            try:
                where, params = self._comp_clause(comps)
                sql = f"SELECT * FROM {self._table_name}"
                if where:
                    sql += f" WHERE {where}"
                return self._conn.execute(sql, params or None)  # type: ignore[return-value]
            finally:
                self._record("list_all", start)

        return self._cached(key, query)

    def get_by_id(
        self,
        id_value: str | int,
        competencias: str | list[str] | None = None,
    ) -> T | None:
        """Busca um registro pela chave primaria."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.get_by_id:{json.dumps([id_value, comps])}"

        def query() -> T | None:
            start = time.monotonic()
            try:
                sql = f"SELECT * FROM {self._table_name} WHERE {self._id_column} = ?"
                params: list[Any] = [id_value]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                rows = self._conn.execute(sql, params)
                return rows[0] if rows else None  # type: ignore[return-value]
            finally:
                self._record("get_by_id", start)

        return self._cached(key, query)

    def list_by_ids(
        self,
        ids: list[str | int],
        competencias: str | list[str] | None = None,
    ) -> list[T]:
        """Busca registros em lote por lista de IDs."""
        if not ids:
            return []
        comps = normalize_competencias(competencias)
        normalized = sorted(set(str(i) for i in ids))
        key = f"{self._table_name}.list_by_ids:{json.dumps([normalized, comps])}"

        def query() -> list[T]:
            start = time.monotonic()
            try:
                id_ph = ", ".join("?" for _ in normalized)
                sql = (
                    f"SELECT * FROM {self._table_name} "
                    f"WHERE {self._id_column} IN ({id_ph})"
                )
                params: list[Any] = list(normalized)
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("list_by_ids", start)

        return self._cached(key, query)

    def search(
        self,
        column: str,
        pattern: str,
        competencias: str | list[str] | None = None,
        limit: int = 50,
    ) -> list[T]:
        """Busca textual (LIKE) em uma coluna."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.search:{json.dumps([column, pattern, comps, limit])}"

        def query() -> list[T]:
            start = time.monotonic()
            try:
                sql = (
                    f"SELECT * FROM {self._table_name} "
                    f"WHERE LOWER({column}) LIKE ?"
                )
                params: list[Any] = [f"%{pattern.lower()}%"]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                sql += f" LIMIT {limit}"
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("search", start)

        return self._cached(key, query)
