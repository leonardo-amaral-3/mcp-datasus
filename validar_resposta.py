"""Backward-compat wrapper — real code in manual_sih_rag.validation.validar_resposta."""

from manual_sih_rag.validation.validar_resposta import (  # noqa: F401
    exec_verificar_citacao,
    extrair_citacoes,
    filtrar_por_relevancia,
    formatar_rodape_verificacao,
    grounding_check,
    pos_llm_validar,
    pre_llm_validar,
    reformular_query,
    verificar_citacao_no_db,
    verificar_todas_citacoes,
)
