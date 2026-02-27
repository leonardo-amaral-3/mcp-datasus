"""Resources especializados CNES com metodos custom alem do BaseResource."""

from __future__ import annotations

import json
import time
from typing import Any

from ..base_resource import BaseResource, normalize_competencias
from ..cache import QueryCache
from ..connection import DuckDBConnection
from ..metrics import MetricsCollector
from . import types as T


class ServicosResource(BaseResource[T.Servico]):
    """Servicos CNES com busca por estabelecimento."""

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(
            conn, "tb_servico_cnes", "co_servico", cache, metrics,
        )

    def list_by_cnes(
        self,
        cnes: str,
        competencias: str | list[str] | None = None,
    ) -> list[T.Servico]:
        """Lista servicos de um estabelecimento CNES."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.list_by_cnes:{json.dumps([cnes, comps])}"

        def query() -> list[T.Servico]:
            start = time.monotonic()
            try:
                sql = f"SELECT * FROM {self._table_name} WHERE cnes = ?"
                params: list[Any] = [cnes]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("list_by_cnes", start)

        return self._cached(key, query)


class ProfissionaisResource(BaseResource[T.Profissional]):
    """Profissionais CNES com busca por estabelecimento e ocupacao."""

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(
            conn, "tb_profissional_cnes", "co_profissional_sus", cache, metrics,
        )

    def list_by_cnes(
        self,
        cnes: str,
        competencias: str | list[str] | None = None,
    ) -> list[T.Profissional]:
        """Lista profissionais de um estabelecimento."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.list_by_cnes:{json.dumps([cnes, comps])}"

        def query() -> list[T.Profissional]:
            start = time.monotonic()
            try:
                sql = f"SELECT * FROM {self._table_name} WHERE cnes = ?"
                params: list[Any] = [cnes]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("list_by_cnes", start)

        return self._cached(key, query)

    def list_by_cnes_e_ocupacao(
        self,
        cnes: str,
        co_ocupacao: str,
        competencias: str | list[str] | None = None,
    ) -> list[T.Profissional]:
        """Lista profissionais por CNES e ocupacao (CBO)."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.list_by_cnes_e_ocupacao:{json.dumps([cnes, co_ocupacao, comps])}"

        def query() -> list[T.Profissional]:
            start = time.monotonic()
            try:
                sql = (
                    f"SELECT * FROM {self._table_name} "
                    f"WHERE cnes = ? AND co_ocupacao = ?"
                )
                params: list[Any] = [cnes, co_ocupacao]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("list_by_cnes_e_ocupacao", start)

        return self._cached(key, query)


class LeitosResource(BaseResource[T.Leito]):
    """Leitos CNES com busca por estabelecimento."""

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        super().__init__(
            conn, "tb_leito_cnes", "co_leito", cache, metrics,
        )

    def list_by_cnes(
        self,
        cnes: str,
        competencias: str | list[str] | None = None,
    ) -> list[T.Leito]:
        """Lista leitos de um estabelecimento."""
        comps = normalize_competencias(competencias)
        key = f"{self._table_name}.list_by_cnes:{json.dumps([cnes, comps])}"

        def query() -> list[T.Leito]:
            start = time.monotonic()
            try:
                sql = f"SELECT * FROM {self._table_name} WHERE cnes = ?"
                params: list[Any] = [cnes]
                where, comp_params = self._comp_clause(comps)
                if where:
                    sql += f" AND {where}"
                    params.extend(comp_params)
                return self._conn.execute(sql, params)  # type: ignore[return-value]
            finally:
                self._record("list_by_cnes", start)

        return self._cached(key, query)
