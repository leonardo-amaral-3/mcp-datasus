"""Tratamento padronizado de erros para tools MCP."""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable

log = logging.getLogger("manual_sih_rag.errors")


class AuditoriaError(Exception):
    """Erro base para o sistema de auditoria."""


class DadosNaoEncontrados(AuditoriaError):
    """Registro nao encontrado no SIGTAP/CNES."""


class ConexaoError(AuditoriaError):
    """Falha de conexao com DuckDB ou MinIO."""


class CompetenciaInvalida(AuditoriaError):
    """Competencia em formato invalido ou inexistente."""


def erro_json(msg: str, **extra: Any) -> str:
    """Retorna erro padronizado em JSON."""
    data: dict[str, Any] = {"erro": msg}
    data.update(extra)
    return json.dumps(data, ensure_ascii=False, indent=2)


def safe_tool(fn: Callable[..., str]) -> Callable[..., str]:
    """Decorator que captura excecoes e retorna JSON de erro padronizado.

    Uso:
        @mcp.tool()
        @safe_tool
        def minha_tool(...) -> str:
            ...
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            return fn(*args, **kwargs)
        except AuditoriaError as e:
            log.warning("Erro de auditoria em %s: %s", fn.__name__, e)
            return erro_json(str(e), tool=fn.__name__)
        except Exception as e:
            log.exception("Erro inesperado em %s", fn.__name__)
            return erro_json(
                f"Erro interno: {type(e).__name__}: {e}",
                tool=fn.__name__,
            )

    return wrapper
