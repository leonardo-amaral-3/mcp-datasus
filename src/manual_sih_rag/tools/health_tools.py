"""Tools MCP de health check, diagnostico e metricas do servidor."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

from . import _json

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..datasus.client import DatasusClient

RAGLoader = Callable[[], tuple[Any, Any, list]]


def register(
    mcp: "FastMCP",
    get_rag: RAGLoader,
    get_datasus: Callable[[], "DatasusClient"],
) -> None:
    """Registra 2 tools de diagnostico e saude do servidor."""

    @mcp.tool()
    def health_check() -> str:
        """Verifica a saude de todos os subsistemas do servidor MCP.

        Testa conectividade com RAG (ChromaDB), DuckDB/SIGTAP e CNES.
        Retorna status de cada subsistema e competencias disponiveis.
        Use para diagnosticar problemas de conectividade ou dados.
        """
        checks: dict[str, dict] = {}

        # 1. RAG (ChromaDB + modelo)
        try:
            start = time.monotonic()
            model, collection, mapeamento = get_rag()
            elapsed = round((time.monotonic() - start) * 1000)
            chunk_count = collection.count() if collection else 0
            checks["rag"] = {
                "status": "ok",
                "chunks_indexados": chunk_count,
                "criticas_mapeadas": len(mapeamento or []),
                "tempo_ms": elapsed,
            }
        except Exception as e:
            checks["rag"] = {"status": "erro", "mensagem": str(e)}

        # 2. DATASUS (DuckDB + MinIO/S3)
        try:
            start = time.monotonic()
            client = get_datasus()
            ok = client.test_connection()
            elapsed = round((time.monotonic() - start) * 1000)

            if ok:
                comp_s = client.ultima_competencia("SIGTAP")
                comp_c = client.ultima_competencia("CNES")
                checks["datasus"] = {
                    "status": "ok",
                    "competencia_sigtap": comp_s,
                    "competencia_cnes": comp_c,
                    "tempo_ms": elapsed,
                }
            else:
                checks["datasus"] = {"status": "erro", "mensagem": "Conexao falhou"}
        except Exception as e:
            checks["datasus"] = {"status": "erro", "mensagem": str(e)}

        # 3. Cache
        try:
            client = get_datasus()
            checks["cache"] = {
                "status": "ok",
                "entradas": client._cache.size,
                "ttl_seconds": client._cache._ttl,
            }
        except Exception:
            checks["cache"] = {"status": "indisponivel"}

        all_ok = all(c.get("status") == "ok" for c in checks.values())
        return _json({
            "status": "ok" if all_ok else "degradado",
            "checks": checks,
        })

    @mcp.tool()
    def info_servidor() -> str:
        """Retorna informacoes completas sobre o servidor MCP.

        Inclui versao, total de tools, competencias disponiveis,
        metricas de performance e estado do cache.
        Use para visao geral do sistema.
        """
        from manual_sih_rag.config import VERSION

        info: dict[str, Any] = {
            "versao": VERSION,
            "total_tools": 43,
            "modulos_tools": [
                "rag_tools (10)", "legacy_tools (6)", "sigtap_tools (12)",
                "cnes_tools (6)", "auditoria_tools (3)",
                "auditoria_aih_tools (2)", "inteligencia_tools (2)",
                "health_tools (2)",
            ],
            "descricao": "Servico de auditoria de faturamento hospitalar SIH/SUS",
        }

        # Competencias
        try:
            client = get_datasus()
            comp_s = client.ultima_competencia("SIGTAP")
            comp_c = client.ultima_competencia("CNES")
            info["competencias"] = {
                "sigtap": comp_s,
                "cnes": comp_c,
            }
        except Exception:
            info["competencias"] = {"erro": "DatasusClient indisponivel"}

        # Metricas DATASUS
        try:
            client = get_datasus()
            m = client.metrics
            top_methods = sorted(
                m.by_method.items(),
                key=lambda x: x[1].query_count,
                reverse=True,
            )[:10]
            info["metricas"] = {
                "total_queries": m.total_queries,
                "total_time_ms": round(m.total_time_ms, 1),
                "avg_time_ms": (
                    round(m.total_time_ms / m.total_queries, 1)
                    if m.total_queries > 0 else 0
                ),
                "cache_hits": m.row_cache_hits,
                "cache_size": client._cache.size,
                "top_methods": [
                    {"method": name, "count": met.query_count,
                     "avg_ms": round(met.total_time_ms / met.query_count, 1)}
                    for name, met in top_methods
                ],
            }
        except Exception:
            info["metricas"] = {"erro": "Metricas indisponiveis"}

        return _json(info)
