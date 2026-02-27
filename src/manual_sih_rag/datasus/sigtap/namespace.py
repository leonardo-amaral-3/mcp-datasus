"""SigtapNamespace — acesso tipado a todas as 41 tabelas SIGTAP."""

from __future__ import annotations

from ..base_resource import BaseResource
from ..cache import QueryCache
from ..connection import DuckDBConnection
from ..metrics import MetricsCollector
from . import types as T
from .resources import ProcedimentoCompativelResource, ProcedimentoResource


class SigtapNamespace:
    """Namespace com acesso a todas as tabelas SIGTAP via BaseResource.

    Uso:
        client.sigtap.procedimentos.get_by_id("0301010072", "202602")
        client.sigtap.cid.search("no_cid", "diabetes", "202602")
        client.sigtap.rl_procedimento_cid.list_by_ids(["0301010072"], "202602")
    """

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        kw = dict(cache=cache, metrics=metrics)

        # ── Tabelas de relacionamento (rl_*) ──────────────────────

        self.rl_excecao_compatibilidade = BaseResource[T.RlExcecaoCompatibilidade](
            conn, "rl_excecao_compatibilidade", "co_procedimento_restricao", **kw
        )
        self.rl_procedimento_cid = BaseResource[T.RlProcedimentoCid](
            conn, "rl_procedimento_cid", "co_procedimento", **kw
        )
        self.rl_procedimento_comp_rede = BaseResource[T.RlProcedimentoCompRede](
            conn, "rl_procedimento_comp_rede", "co_procedimento", **kw
        )
        self.rl_procedimento_compativel = ProcedimentoCompativelResource(conn, **kw)
        self.rl_procedimento_detalhe = BaseResource[T.RlProcedimentoDetalhe](
            conn, "rl_procedimento_detalhe", "co_procedimento", **kw
        )
        self.rl_procedimento_habilitacao = BaseResource[T.RlProcedimentoHabilitacao](
            conn, "rl_procedimento_habilitacao", "co_procedimento", **kw
        )
        self.rl_procedimento_incremento = BaseResource[T.RlProcedimentoIncremento](
            conn, "rl_procedimento_incremento", "co_procedimento", **kw
        )
        self.rl_procedimento_leito = BaseResource[T.RlProcedimentoLeito](
            conn, "rl_procedimento_leito", "co_procedimento", **kw
        )
        self.rl_procedimento_modalidade = BaseResource[T.RlProcedimentoModalidade](
            conn, "rl_procedimento_modalidade", "co_procedimento", **kw
        )
        self.rl_procedimento_ocupacao = BaseResource[T.RlProcedimentoOcupacao](
            conn, "rl_procedimento_ocupacao", "co_procedimento", **kw
        )
        self.rl_procedimento_origem = BaseResource[T.RlProcedimentoOrigem](
            conn, "rl_procedimento_origem", "co_procedimento", **kw
        )
        self.rl_procedimento_registro = BaseResource[T.RlProcedimentoRegistro](
            conn, "rl_procedimento_registro", "co_procedimento", **kw
        )
        self.rl_procedimento_regra_cond = BaseResource[T.RlProcedimentoRegraCond](
            conn, "rl_procedimento_regra_cond", "co_procedimento", **kw
        )
        self.rl_procedimento_renases = BaseResource[T.RlProcedimentoRenases](
            conn, "rl_procedimento_renases", "co_procedimento", **kw
        )
        self.rl_procedimento_servico = BaseResource[T.RlProcedimentoServico](
            conn, "rl_procedimento_servico", "co_procedimento", **kw
        )
        self.rl_procedimento_sia_sih = BaseResource[T.RlProcedimentoSiaSih](
            conn, "rl_procedimento_sia_sih", "co_procedimento", **kw
        )
        self.rl_procedimento_tuss = BaseResource[T.RlProcedimentoTuss](
            conn, "rl_procedimento_tuss", "co_procedimento", **kw
        )

        # ── Tabelas de dominio (tb_*) ────────────────────────────

        self.cid = BaseResource[T.TbCid](
            conn, "tb_cid", "co_cid", **kw
        )
        self.componente_rede = BaseResource[T.TbComponenteRede](
            conn, "tb_componente_rede", "co_componente_rede", **kw
        )
        self.descricao = BaseResource[T.TbDescricao](
            conn, "tb_descricao", "co_procedimento", **kw
        )
        self.descricao_detalhe = BaseResource[T.TbDescricaoDetalhe](
            conn, "tb_descricao_detalhe", "co_detalhe", **kw
        )
        self.detalhe = BaseResource[T.TbDetalhe](
            conn, "tb_detalhe", "co_detalhe", **kw
        )
        self.financiamento = BaseResource[T.TbFinanciamento](
            conn, "tb_financiamento", "co_financiamento", **kw
        )
        self.forma_organizacao = BaseResource[T.TbFormaOrganizacao](
            conn, "tb_forma_organizacao", "co_grupo", **kw
        )
        self.grupos = BaseResource[T.TbGrupo](
            conn, "tb_grupo", "co_grupo", **kw
        )
        self.grupo_habilitacao = BaseResource[T.TbGrupoHabilitacao](
            conn, "tb_grupo_habilitacao", "nu_grupo_habilitacao", **kw
        )
        self.habilitacao = BaseResource[T.TbHabilitacao](
            conn, "tb_habilitacao", "co_habilitacao", **kw
        )
        self.modalidade = BaseResource[T.TbModalidade](
            conn, "tb_modalidade", "co_modalidade", **kw
        )
        self.ocupacao = BaseResource[T.TbOcupacao](
            conn, "tb_ocupacao", "co_ocupacao", **kw
        )
        self.procedimentos = ProcedimentoResource(conn, **kw)
        self.rede_atencao = BaseResource[T.TbRedeAtencao](
            conn, "tb_rede_atencao", "co_rede_atencao", **kw
        )
        self.registro = BaseResource[T.TbRegistro](
            conn, "tb_registro", "co_registro", **kw
        )
        self.regra_condicionada = BaseResource[T.TbRegraCondicionada](
            conn, "tb_regra_condicionada", "co_regra_condicionada", **kw
        )
        self.renases = BaseResource[T.TbRenases](
            conn, "tb_renases", "co_renases", **kw
        )
        self.rubrica = BaseResource[T.TbRubrica](
            conn, "tb_rubrica", "co_rubrica", **kw
        )
        self.servico = BaseResource[T.TbServico](
            conn, "tb_servico", "co_servico", **kw
        )
        self.servico_classificacao = BaseResource[T.TbServicoClassificacao](
            conn, "tb_servico_classificacao", "co_servico", **kw
        )
        self.sia_sih = BaseResource[T.TbSiaSih](
            conn, "tb_sia_sih", "co_procedimento_sia_sih", **kw
        )
        self.sub_grupo = BaseResource[T.TbSubGrupo](
            conn, "tb_sub_grupo", "co_grupo", **kw
        )
        self.tipo_leito = BaseResource[T.TbTipoLeito](
            conn, "tb_tipo_leito", "co_tipo_leito", **kw
        )
        self.tuss = BaseResource[T.TbTuss](
            conn, "tb_tuss", "co_tuss", **kw
        )
