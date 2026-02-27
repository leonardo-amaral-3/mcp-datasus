"""RAG pipeline for Manual SIH/SUS."""

from .aih_parser import extrair_dados_aih, ler_texto_multilinhas
from .engine import buscar, carregar_sistema
from .hints import CRITICA_HINTS, GRUPO_SIGTAP
from .paths import DATA_DIR, DB_DIR, PROJECT_ROOT

__all__ = [
    "buscar",
    "carregar_sistema",
    "extrair_dados_aih",
    "ler_texto_multilinhas",
    "CRITICA_HINTS",
    "GRUPO_SIGTAP",
    "DATA_DIR",
    "DB_DIR",
    "PROJECT_ROOT",
]
