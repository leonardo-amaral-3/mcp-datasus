"""Document extraction subsystem."""

from .pdf_extractor import (
    criar_chunks,
    detectar_secoes,
    extrair_generico,
    extrair_texto_paginas,
)

__all__ = [
    "criar_chunks",
    "detectar_secoes",
    "extrair_generico",
    "extrair_texto_paginas",
]
