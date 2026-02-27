#!/bin/bash
# Setup do sistema RAG Manual SIH/SUS + MCP Server
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=== Manual SIH/SUS — Setup ==="
echo ""

# 1. Ambiente virtual
if [ ! -d ".venv" ]; then
    echo "[1/4] Criando ambiente virtual..."
    python3 -m venv .venv
else
    echo "[1/4] Ambiente virtual já existe."
fi
source .venv/bin/activate

# 2. Dependências
echo "[2/4] Instalando dependências..."
pip install -e . -q

# 3. Extração + indexação (se ragData existir e db não)
if [ -d "ragData" ] && [ ! -d "db" ]; then
    echo "[3/4] Extraindo e indexando documentos..."
    python extrair_manual.py --ragdata ragData/
    python indexar_manual.py
elif [ -d "db" ]; then
    echo "[3/4] Banco vetorial já existe. Para reindexar:"
    echo "       python extrair_manual.py --ragdata ragData/"
    echo "       python indexar_manual.py"
else
    echo "[3/4] Sem ragData/ — coloque PDFs em ragData/manuais/ e rode novamente."
fi

# 4. Registrar MCP
echo "[4/4] Registrando MCP server no Claude Code..."
if command -v claude &>/dev/null; then
    claude mcp add manual-sih -- "$DIR/.venv/bin/python" "$DIR/mcp_server.py"
    echo "       MCP registrado como 'manual-sih' (local)."
    echo ""
    echo "  Para registro global (qualquer repo):"
    echo "    pip install -e $DIR"
    echo "    claude mcp add --scope user manual-sih -- manual-sih-mcp"
else
    echo "  'claude' CLI não encontrado. Instale e rode:"
    echo "    claude mcp add manual-sih -- $DIR/.venv/bin/python $DIR/mcp_server.py"
fi

echo ""
echo "=== Setup completo! ==="
echo ""
echo "Uso:"
echo "  python consulta_manual.py                      # Consulta interativa"
echo "  python consulta_manual.py 'sua pergunta'       # Consulta direta"
echo ""
echo "MCP Server (16 tools):"
echo "  Abra nova sessão do Claude Code — tools disponíveis automaticamente."
echo ""
echo "SIGTAP/CNES (opcional):"
echo "  Precisa de MinIO rodando com dados DATASUS."
echo "  Copie .env.example para .env e configure."
echo ""
