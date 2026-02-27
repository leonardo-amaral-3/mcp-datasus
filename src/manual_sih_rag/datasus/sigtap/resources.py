"""Resources especializados SIGTAP com metodos custom alem do BaseResource."""

from __future__ import annotations

import json
import time
from typing import Any

from ..base_resource import BaseResource, normalize_competencias
from ..cache import QueryCache
from ..connection import DuckDBConnection
from ..metrics import MetricsCollector
from . import types as T


class ProcedimentoCompativelResource(BaseResource[T.RlProcedimentoCompativel]):
    """Compatibilidades entre procedimentos — busca bidirecional."""

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(
            conn, "rl_procedimento_compativel", "co_procedimento_principal",
            cache, metrics,
        )

    def list_by_procedimentos(
        self,
        codigos: list[str],
        competencias: str | list[str] | None = None,
    ) -> list[T.RlProcedimentoCompativel]:
        """Busca compatibilidades onde o procedimento aparece como principal OU compativel."""
        if not codigos:
            return []
        comps = normalize_competencias(competencias)
        normalized = sorted(set(codigos))
        key = f"{self._table_name}.list_by_procedimentos:{json.dumps([normalized, comps])}"

        def query() -> list[T.RlProcedimentoCompativel]:
            start = time.monotonic()
            try:
                id_ph = ", ".join("?" for _ in normalized)
                sql = (
                    f"SELECT * FROM {self._table_name} "
                    f"WHERE (co_procedimento_principal IN ({id_ph}) "
                    f"OR co_procedimento_compativel IN ({id_ph}))"
                )
                params: list[Any] = [*normalized, *normalized]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("list_by_procedimentos", start)

        return self._cached(key, query)


class ProcedimentoResource(BaseResource[T.TbProcedimento]):
    """Procedimentos SIGTAP com busca por nome e hierarquia."""

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(
            conn, "tb_procedimento", "co_procedimento", cache, metrics,
        )

    def buscar_por_nome(
        self,
        nome: str,
        competencias: str | list[str] | None = None,
        limit: int = 50,
    ) -> list[T.TbProcedimento]:
        """Busca procedimentos por nome (case-insensitive, sem acento)."""
        return self.search("no_procedimento_normalizado", nome, competencias, limit)

    def buscar_por_grupo(
        self,
        co_grupo: str,
        competencias: str | list[str] | None = None,
    ) -> list[T.TbProcedimento]:
        """Busca procedimentos cujo codigo comeca com o grupo."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.buscar_por_grupo:{json.dumps([co_grupo, comps])}"

        def query() -> list[T.TbProcedimento]:
            start = time.monotonic()
            try:
                sql = (
                    f"SELECT * FROM {self._table_name} "
                    f"WHERE co_procedimento LIKE ?"
                )
                params: list[Any] = [f"{co_grupo}%"]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("buscar_por_grupo", start)

        return self._cached(key, query)
