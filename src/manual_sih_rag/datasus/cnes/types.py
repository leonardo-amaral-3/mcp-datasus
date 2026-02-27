"""TypedDicts para as 5 tabelas CNES.

Baseado nos schemas do processos-core/src/v1/datasusClient/cnes/types.ts.
"""

from __future__ import annotations

from typing import TypedDict


class Profissional(TypedDict):
    cnes: str
    co_ocupacao: str
    co_profissional_sus: str
    co_vinculacao: str
    dt_competencia: str
    qt_vinculos_publicos_profissional: str | None
    qt_carga_horaria_total_profissional: str | None


class DadosProfissional(TypedDict):
    cnes: str
    co_profissional_sus: str
    co_cpf: str
    co_cns: str
    dt_competencia: str


class Leito(TypedDict):
    cnes: str
    co_leito: str
    co_tipo_leito: str
    dt_competencia: str
    quantidade_sus: str


class Habilitacao(TypedDict):
    cnes: str
    cod_sub_grupo_habilitacao: str
    dt_competencia: str


class Servico(TypedDict):
    cnes: str
    co_servico: str
    co_classificacao: str
    tp_caracteristica: str
    co_cnpjcpf: str
    dt_competencia: str
