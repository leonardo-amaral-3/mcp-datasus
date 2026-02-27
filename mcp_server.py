"""
MCP Server para o sistema RAG do Manual SIH/SUS.

Expoe as ferramentas de busca semantica, analise de criticas e consulta
ao manual como tools MCP para uso direto no Claude Code.

Registro local:
  claude mcp add manual-sih -- .venv/bin/python mcp_server.py

Registro global (qualquer repo):
  claude mcp add --scope user manual-sih -- manual-sih-mcp
"""

import json
import os
import sys
from pathlib import Path

_BASE = Path(__file__).parent
sys.path.insert(0, str(_BASE))
sys.path.insert(0, str(_BASE / "src"))
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from mcp.server.fastmcp import FastMCP

_MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
_MCP_PORT = int(os.getenv("MCP_PORT", "8200"))

mcp = FastMCP(
    "manual-sih",
    host=_MCP_HOST,
    port=_MCP_PORT,
    instructions=(
        "Servidor RAG para consulta do Manual Tecnico SIH/SUS, SIA/SUS e portarias. "
        "Permite busca semantica no manual, analise de criticas de validacao, "
        "consulta de secoes especificas e extracao de dados de AIH. "
        "Tambem consulta SIGTAP (procedimentos SUS) e CNES (dados de estabelecimentos) via MinIO. "
        "SEMPRE use buscar_manual antes de responder perguntas sobre regras SIH/SUS. "
        "Use consultar_procedimento para validar codigos e valores de procedimentos. "
        "Use consultar_cnes para verificar leitos, servicos e habilitacoes de um estabelecimento. "
        "Use auditar_aih para auditoria completa de uma AIH (procedimento + CID + CNES + profissional). "
        "Use calcular_valor_aih para calcular valores com incrementos. "
        "Use sugerir_procedimentos_por_cid para encontrar procedimentos a partir de um diagnostico. "
        "Cite secoes e paginas no formato [Secao X.Y, p.N]. "
        "Use verificar_citacao para confirmar que uma secao existe antes de cita-la.\n\n"
        "FORMATACAO DE RESULTADOS:\n"
        "Ao apresentar resultados de auditoria (auditar_aih, validar_procedimento_cnes, etc), "
        "SEMPRE formate como relatorio legivel com:\n"
        "1. Resumo com status (CONFORME / NAO CONFORME) em destaque\n"
        "2. Tabela de validacoes com colunas: Item | Status | Detalhe\n"
        "3. Lista de alertas (se houver) com explicacao do impacto\n"
        "4. Valor estimado da AIH formatado em reais (R$)\n"
        "5. Recomendacoes quando nao conforme\n"
        "NUNCA mostre JSON cru ao usuario. Sempre interprete e formate os dados.\n"
        "Use emojis de status: conforme, alerta, erro para facilitar leitura.\n"
        "Quando o procedimento nao for encontrado, use buscar_procedimento para "
        "sugerir codigos similares antes de reportar erro."
    ),
)

# ---------------------------------------------------------------------------
# Lazy RAG system
# ---------------------------------------------------------------------------
_rag_state: dict = {
    "model": None, "collection": None, "mapeamento": None, "loaded": False
}


def _get_rag():
    """Lazy-load do sistema RAG (model + collection + mapeamento)."""
    if not _rag_state["loaded"]:
        from manual_sih_rag.rag import carregar_sistema

        _rag_state["model"], _rag_state["collection"] = carregar_sistema()
        mapeamento_path = _BASE / "data" / "mapeamento_criticas_manual.json"
        if mapeamento_path.exists():
            _rag_state["mapeamento"] = json.loads(
                mapeamento_path.read_text(encoding="utf-8")
            )
        else:
            _rag_state["mapeamento"] = []
        _rag_state["loaded"] = True
    return _rag_state["model"], _rag_state["collection"], _rag_state["mapeamento"]


# ---------------------------------------------------------------------------
# Lazy DATASUS client (DuckDB)
# ---------------------------------------------------------------------------
_datasus_client = None


def _get_datasus():
    """Lazy-load do DatasusClient."""
    global _datasus_client
    if _datasus_client is None:
        from manual_sih_rag.config import load_settings
        from manual_sih_rag.datasus.client import DatasusClient

        _datasus_client = DatasusClient.from_settings(load_settings())
    return _datasus_client


# ---------------------------------------------------------------------------
# Register all tool modules
# ---------------------------------------------------------------------------
from manual_sih_rag.tools.rag_tools import register as _reg_rag
from manual_sih_rag.tools.legacy_tools import register as _reg_legacy
from manual_sih_rag.tools.sigtap_tools import register as _reg_sigtap
from manual_sih_rag.tools.cnes_tools import register as _reg_cnes
from manual_sih_rag.tools.auditoria_tools import register as _reg_auditoria
from manual_sih_rag.tools.auditoria_aih_tools import register as _reg_aih
from manual_sih_rag.tools.inteligencia_tools import register as _reg_intel
from manual_sih_rag.tools.health_tools import register as _reg_health

_reg_rag(mcp, _get_rag)
_reg_legacy(mcp)
_reg_sigtap(mcp, _get_datasus)
_reg_cnes(mcp, _get_datasus)
_reg_auditoria(mcp, _get_datasus)
_reg_aih(mcp, _get_datasus)
_reg_intel(mcp, _get_datasus)
_reg_health(mcp, _get_rag, _get_datasus)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def main():
    import argparse

    parser = argparse.ArgumentParser(description="MCP Server Manual SIH/SUS")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transporte MCP (default: stdio)",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


def main_server():
    """Entry point para modo SSE (servidor compartilhado)."""
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
