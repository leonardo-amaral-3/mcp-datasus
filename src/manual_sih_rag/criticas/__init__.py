"""Critica validation and analysis subsystem."""

from .validar import (
    buscar_manual,
    extrair_logica_hasCritica,
    extrair_termos_busca,
    ler_codigo_critica,
    ler_definicao_critica,
    listar_arquivos_critica,
)

from .analisar import (
    PROMPT_SISTEMA,
    analisar_uma_critica,
    montar_prompt,
)

__all__ = [
    "buscar_manual",
    "extrair_logica_hasCritica",
    "extrair_termos_busca",
    "ler_codigo_critica",
    "ler_definicao_critica",
    "listar_arquivos_critica",
    "PROMPT_SISTEMA",
    "analisar_uma_critica",
    "montar_prompt",
]
