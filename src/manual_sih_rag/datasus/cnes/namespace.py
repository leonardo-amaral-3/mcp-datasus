"""CnesNamespace — acesso tipado a todas as 5 tabelas CNES."""

from __future__ import annotations

from ..base_resource import BaseResource
from ..cache import QueryCache
from ..connection import DuckDBConnection
from ..metrics import MetricsCollector
from . import types as T
from .resources import LeitosResource, ProfissionaisResource, ServicosResource


class CnesNamespace:
    """Namespace com acesso a todas as tabelas CNES.

    Uso:
        client.cnes.profissionais.list_by_cnes("2077485", "202602")
        client.cnes.leitos.list_by_cnes("2077485", "202602")
        client.cnes.servicos.list_by_cnes("2077485", "202602")
        client.cnes.habilitacoes.list_by_ids(["2077485"], "202602")
    """

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        kw = dict(cache=cache, metrics=metrics)

        self.profissionais = ProfissionaisResource(conn, **kw)

        self.dados_profissionais = BaseResource[T.DadosProfissional](
            conn, "tb_dados_profissionais_cnes", "co_profissional_sus", **kw
        )

        self.leitos = LeitosResource(conn, **kw)

        self.habilitacoes = BaseResource[T.Habilitacao](
            conn, "tb_habilitacao_cnes", "cod_sub_grupo_habilitacao", **kw
        )

        self.servicos = ServicosResource(conn, **kw)
