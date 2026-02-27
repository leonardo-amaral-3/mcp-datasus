"""TypedDicts para todas as 41 tabelas SIGTAP.

Baseado nos schemas do processos-core/src/v1/datasusClient/sigtap/types.ts.
Todos os campos sao str pois os Parquet DATASUS usam VARCHAR.
"""

from __future__ import annotations

from typing import TypedDict


# ── Tabelas de relacionamento (rl_*) ──────────────────────────────


class RlExcecaoCompatibilidade(TypedDict):
    co_procedimento_restricao: str
    co_procedimento_principal: str
    co_registro_principal: str
    co_procedimento_compativel: str
    co_registro_compativel: str
    tp_compatibilidade: str
    dt_competencia: str


class RlProcedimentoCid(TypedDict):
    co_procedimento: str
    co_cid: str
    st_principal: str
    dt_competencia: str


class RlProcedimentoCompRede(TypedDict):
    co_procedimento: str
    co_componente_rede: str
    dt_competencia: str


class RlProcedimentoCompativel(TypedDict):
    co_procedimento_principal: str
    co_registro_principal: str
    co_procedimento_compativel: str
    co_registro_compativel: str
    tp_compatibilidade: str
    qt_permitida: str
    dt_competencia: str


class RlProcedimentoDetalhe(TypedDict):
    co_procedimento: str
    co_detalhe: str
    dt_competencia: str


class RlProcedimentoHabilitacao(TypedDict):
    co_procedimento: str
    co_habilitacao: str
    nu_grupo_habilitacao: str
    dt_competencia: str


class RlProcedimentoIncremento(TypedDict):
    co_procedimento: str
    co_habilitacao: str
    vl_percentual_sh: str
    vl_percentual_sa: str
    vl_percentual_sp: str
    dt_competencia: str


class RlProcedimentoLeito(TypedDict):
    co_procedimento: str
    co_tipo_leito: str
    dt_competencia: str


class RlProcedimentoModalidade(TypedDict):
    co_procedimento: str
    co_modalidade: str
    dt_competencia: str


class RlProcedimentoOcupacao(TypedDict):
    co_procedimento: str
    co_ocupacao: str
    dt_competencia: str


class RlProcedimentoOrigem(TypedDict):
    co_procedimento: str
    co_procedimento_origem: str
    dt_competencia: str


class RlProcedimentoRegistro(TypedDict):
    co_procedimento: str
    co_registro: str
    dt_competencia: str


class RlProcedimentoRegraCond(TypedDict):
    co_procedimento: str
    co_regra_condicionada: str
    dt_competencia: str


class RlProcedimentoRenases(TypedDict):
    co_procedimento: str
    co_renases: str
    dt_competencia: str


class RlProcedimentoServico(TypedDict):
    co_procedimento: str
    co_servico: str
    co_classificacao: str
    dt_competencia: str


class RlProcedimentoSiaSih(TypedDict):
    co_procedimento: str
    co_procedimento_sia_sih: str
    tp_procedimento: str
    dt_competencia: str


class RlProcedimentoTuss(TypedDict):
    co_procedimento: str
    co_tuss: str
    dt_competencia: str


# ── Tabelas de dominio (tb_*) ─────────────────────────────────────


class TbCid(TypedDict):
    co_cid: str
    no_cid: str
    tp_agravo: str
    tp_sexo: str
    tp_estadio: str
    vl_campos_irradiados: str
    dt_competencia: str


class TbComponenteRede(TypedDict):
    co_componente_rede: str
    no_componente_rede: str
    co_rede_atencao: str
    dt_competencia: str


class TbDescricao(TypedDict):
    co_procedimento: str
    ds_procedimento: str
    dt_competencia: str
    ds_procedimento_normalizada: str


class TbDescricaoDetalhe(TypedDict):
    co_detalhe: str
    ds_detalhe: str
    dt_competencia: str


class TbDetalhe(TypedDict):
    co_detalhe: str
    no_detalhe: str
    dt_competencia: str


class TbFinanciamento(TypedDict):
    co_financiamento: str
    no_financiamento: str
    dt_competencia: str


class TbFormaOrganizacao(TypedDict):
    co_grupo: str
    co_sub_grupo: str
    co_forma_organizacao: str
    no_forma_organizacao: str
    dt_competencia: str


class TbGrupo(TypedDict):
    co_grupo: str
    no_grupo: str
    dt_competencia: str


class TbGrupoHabilitacao(TypedDict):
    nu_grupo_habilitacao: str
    no_grupo_habilitacao: str
    ds_grupo_habilitacao: str
    dt_competencia: str


class TbHabilitacao(TypedDict):
    co_habilitacao: str
    no_habilitacao: str
    dt_competencia: str


class TbModalidade(TypedDict):
    co_modalidade: str
    no_modalidade: str
    dt_competencia: str


class TbOcupacao(TypedDict):
    co_ocupacao: str
    no_ocupacao: str
    dt_competencia: str


class TbProcedimento(TypedDict):
    co_procedimento: str
    no_procedimento: str
    tp_complexidade: str
    tp_sexo: str
    qt_maxima_execucao: str
    qt_dias_permanencia: str
    qt_pontos: str
    vl_idade_minima: str
    vl_idade_maxima: str
    vl_sh: str
    vl_sa: str
    vl_sp: str
    co_financiamento: str
    co_rubrica: str
    qt_tempo_permanencia: str
    dt_competencia: str
    vl_total_hospitalar: str
    no_procedimento_normalizado: str


class TbRedeAtencao(TypedDict):
    co_rede_atencao: str
    no_rede_atencao: str
    dt_competencia: str


class TbRegistro(TypedDict):
    co_registro: str
    no_registro: str
    dt_competencia: str


class TbRegraCondicionada(TypedDict):
    co_regra_condicionada: str
    no_regra_condicionada: str
    ds_regra_condicionada: str
    dt_competencia: str


class TbRenases(TypedDict):
    co_renases: str
    no_renases: str
    dt_competencia: str


class TbRubrica(TypedDict):
    co_rubrica: str
    no_rubrica: str
    dt_competencia: str


class TbServico(TypedDict):
    co_servico: str
    no_servico: str
    dt_competencia: str


class TbServicoClassificacao(TypedDict):
    co_servico: str
    co_classificacao: str
    no_classificacao: str
    dt_competencia: str


class TbSiaSih(TypedDict):
    co_procedimento_sia_sih: str
    no_procedimento_sia_sih: str
    tp_procedimento: str
    dt_competencia: str


class TbSubGrupo(TypedDict):
    co_grupo: str
    co_sub_grupo: str
    no_sub_grupo: str
    dt_competencia: str


class TbTipoLeito(TypedDict):
    co_tipo_leito: str
    no_tipo_leito: str
    dt_competencia: str


class TbTuss(TypedDict):
    co_tuss: str
    no_tuss: str
    dt_competencia: str
