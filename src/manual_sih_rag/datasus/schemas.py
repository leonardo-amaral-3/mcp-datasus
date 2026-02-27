"""Mapeamento de tabelas DATASUS para arquivos Parquet no S3.

SIGTAP: nome da view == nome do arquivo (sem .parquet).
CNES: mapeamento view_name -> file_name.
"""

# SIGTAP: 41 tabelas — nome do parquet = nome da tabela
SIGTAP_TABLES: list[str] = [
    "rl_excecao_compatibilidade",
    "rl_procedimento_cid",
    "rl_procedimento_comp_rede",
    "rl_procedimento_compativel",
    "rl_procedimento_detalhe",
    "rl_procedimento_habilitacao",
    "rl_procedimento_incremento",
    "rl_procedimento_leito",
    "rl_procedimento_modalidade",
    "rl_procedimento_ocupacao",
    "rl_procedimento_origem",
    "rl_procedimento_registro",
    "rl_procedimento_regra_cond",
    "rl_procedimento_renases",
    "rl_procedimento_servico",
    "rl_procedimento_sia_sih",
    "rl_procedimento_tuss",
    "tb_cid",
    "tb_componente_rede",
    "tb_descricao",
    "tb_descricao_detalhe",
    "tb_detalhe",
    "tb_financiamento",
    "tb_forma_organizacao",
    "tb_grupo",
    "tb_grupo_habilitacao",
    "tb_habilitacao",
    "tb_modalidade",
    "tb_ocupacao",
    "tb_procedimento",
    "tb_rede_atencao",
    "tb_registro",
    "tb_regra_condicionada",
    "tb_renases",
    "tb_rubrica",
    "tb_servico",
    "tb_servico_classificacao",
    "tb_sia_sih",
    "tb_sub_grupo",
    "tb_tipo_leito",
    "tb_tuss",
]

# CNES: 5 tabelas — view_name -> parquet file name
CNES_TABLES: dict[str, str] = {
    "tb_profissional_cnes": "profissionais.parquet",
    "tb_dados_profissionais_cnes": "dadosProfissionais.parquet",
    "tb_leito_cnes": "leitos.parquet",
    "tb_habilitacao_cnes": "habilitacoes.parquet",
    "tb_servico_cnes": "servicos.parquet",
}
