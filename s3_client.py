"""Backward-compat wrapper — real code in manual_sih_rag.legacy.s3_client."""

from manual_sih_rag.legacy.s3_client import (  # noqa: F401
    _get_client,
    ler_parquet,
    listar_arquivos,
    listar_competencias,
    ultima_competencia,
)
