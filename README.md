# Manual RAG — Sistema de Consulta SIH/SUS

Sistema RAG (Retrieval-Augmented Generation) para consulta dos manuais do SIH/SUS, SIA/SUS e portarias relacionadas em linguagem natural, com agente de análise crítica por IA.

Funciona como **MCP Server** para o Claude Code, expondo 16 tools para consulta do manual, críticas, SIGTAP e CNES.

## Instalação rápida

```bash
cd scripts/manual-rag
bash setup.sh
```

O script cria o venv, instala dependências, indexa os documentos (se existirem em `ragData/`) e registra o MCP server no Claude Code.

## Instalação manual

### 1. Ambiente e dependências

```bash
cd scripts/manual-rag
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Alimentar o banco vetorial

Coloque PDFs em `ragData/manuais/` e portarias em `ragData/portarias/`, depois:

```bash
python extrair_manual.py --ragdata ragData/
python indexar_manual.py
```

### 3. Registrar MCP no Claude Code

```bash
# Local (este repo)
claude mcp add manual-sih -- .venv/bin/python mcp_server.py

# Global (qualquer repo)
pip install -e .
claude mcp add --scope user manual-sih -- manual-sih-mcp
```

Abra uma nova sessão do Claude Code — as 16 tools ficam disponíveis automaticamente.

### 4. SIGTAP e CNES (opcional)

As tools de SIGTAP e CNES leem Parquet do MinIO. Precisa do container do `modulo-processos` rodando:

```bash
cd modulo-processos && docker compose up -d minio
```

Copie `.env.example` para `.env` e ajuste se necessário:

```bash
cp .env.example .env
```

### API Key (para `/explicar` e `analisar_critica.py`)

```bash
export GEMINI_API_KEY="sua-chave"
```

Ou salve em arquivo:

```bash
mkdir -p ~/.config/google
echo "sua-chave" > ~/.config/google/api_key
chmod 600 ~/.config/google/api_key
```

## Alimentar o banco

### Opção 1: Processar todo o ragData (recomendado)

Processa recursivamente todos os arquivos em `ragData/` (PDFs, HTMLs, DOCs, ZIPs):

```bash
source .venv/bin/activate
python extrair_manual.py --ragdata ragData/
python indexar_manual.py
```

### Opção 2: PDFs individuais

```bash
# Múltiplos PDFs
python extrair_manual.py manual1.pdf manual2.pdf

# Adicionar sem apagar existentes
python extrair_manual.py --adicionar novo.pdf
```

### Opção 3: Auto-detecção

Se nenhum argumento for passado, procura `*.pdf` no diretório raiz do projeto:

```bash
python extrair_manual.py
```

Após qualquer extração, sempre indexar:

```bash
python indexar_manual.py
```

## Uso

### `consulta_manual.py` — Consulta interativa

Busca semântica no manual em linguagem natural.

```bash
# Modo interativo
python consulta_manual.py

# Consulta direta (uma pergunta)
python consulta_manual.py 'como registrar politraumatizado na AIH'
```

**Comandos no modo interativo:**

| Comando | Ação |
|---------|------|
| `<pergunta>` | Busca semântica no manual |
| `/explicar N` | Explica como a crítica N é validada (usa IA + RAG + código) |
| `/critica` | Modo validação de críticas (busca semântica simples) |
| `/fontes` | Lista todas as fontes indexadas com tipo e ano |
| `/secoes` | Lista todas as seções do manual |
| `/buscar N` | Altera quantidade de resultados (padrão: 5) |
| `sair` | Encerra |

#### `/explicar N` — Como funciona a validação de uma crítica

Combina o código TypeScript da crítica + trechos relevantes do manual + Claude para gerar uma explicação didática:

1. O que a crítica verifica
2. Passo a passo da validação
3. Campos envolvidos
4. Exceções (quando NÃO gera crítica)
5. Fundamentação no manual (com seção e página)

Após a explicação, abre modo interativo para perguntas de follow-up.

```
Manual SIH> /explicar 92
```

### `analisar_critica.py` — Agente de Análise Crítica (IA)

Envia o código + trechos do manual para o Claude e recebe um parecer estruturado de conformidade.

```bash
# Analisar uma crítica
python analisar_critica.py 92

# Analisar e salvar resultado em data/analises/
python analisar_critica.py 92 --salvar

# Analisar TODAS as críticas
python analisar_critica.py --todas --salvar
```

**O parecer inclui:**
- Resumo da regra
- O que o código faz (passo a passo)
- O que o manual diz (com seção e página)
- **Veredicto: CONFORME / PARCIALMENTE CONFORME / NÃO CONFORME**
- Pontos conformes, lacunas, excessos e riscos
- Recomendações concretas

Após a análise, abre modo interativo para perguntas de follow-up com contexto mantido.

**Com `--salvar`**, gera em `data/analises/`:
- `analise_critica_92.json` — dados estruturados
- `analise_critica_92.md` — parecer em markdown

### `validar_critica.py` — Código vs Manual (sem IA)

Mostra o código de uma crítica lado a lado com as seções do manual que a fundamentam.

```bash
python validar_critica.py 129
```

**Comandos internos:** `/codigo` (ver código completo), `/full` (ver todas as seções encontradas)

### `mapear_criticas.py` — Referência cruzada em lote

Mapeia automaticamente todas as críticas de `processos-criticas` para as seções do manual.

```bash
python mapear_criticas.py
```

Gera tabela no terminal e salva `data/mapeamento_criticas_manual.json`.

### `extrair_manual.py` — Extração de texto

```bash
# Processar todo ragData (PDFs, HTMLs, DOCs, ZIPs)
python extrair_manual.py --ragdata ragData/

# PDFs individuais
python extrair_manual.py manual1.pdf manual2.pdf

# Adicionar sem apagar existentes
python extrair_manual.py --adicionar novo.pdf
```

Formatos suportados:
- **PDF**: Manuais SIH/SUS (extração por seções numeradas) ou genérico (por página/parágrafo)
- **HTML/HTM**: Portarias em HTML (encoding windows-1252/latin-1/utf-8)
- **DOC**: Documentos legados (via libreoffice --headless)
- **ZIP**: Extrai e processa recursivamente o conteúdo

Anexos SIGTAP (tabelas de procedimentos) são detectados automaticamente e limitados a 10 páginas.

Salva em `data/chunks.json`.

### `indexar_manual.py` — Indexação vetorial

Gera embeddings e indexa no ChromaDB. Deve ser executado após cada `extrair_manual.py`.

```bash
python indexar_manual.py
```

## MCP Tools (16)

| Tool | Descrição |
|------|-----------|
| `buscar_manual` | Busca semântica no manual SIH/SUS |
| `buscar_critica` | Busca crítica por número |
| `listar_criticas` | Lista críticas com filtro |
| `buscar_por_secao` | Busca seção por número |
| `verificar_citacao` | Verifica se seção existe |
| `extrair_dados_aih` | Extrai dados de espelho de AIH |
| `ler_codigo_critica` | Lê código TypeScript da crítica |
| `contexto_critica` | Contexto completo de uma crítica |
| `listar_fontes` | Fontes indexadas no banco |
| `listar_secoes` | Seções do manual |
| `consultar_procedimento` | Procedimento SIGTAP por código |
| `buscar_procedimento` | Busca SIGTAP por nome |
| `info_sigtap` | Metadata do SIGTAP carregado |
| `consultar_cnes` | Dados operacionais de um CNES |
| `buscar_profissionais_cnes` | Profissionais de um CNES |
| `info_cnes` | Metadata do CNES carregado |

## Estrutura

```
scripts/manual-rag/
  ragData/
    manuais/            # PDFs dos manuais SIH/SUS e SIA/SUS
    portarias/          # Portarias (PDF, HTML, DOC, ZIP)
  data/
    chunks.json         # Chunks extraídos
    secoes.json         # Seções detectadas
    analises/           # Pareceres do agente
  db/                   # Banco vetorial ChromaDB
  mcp_server.py         # MCP Server (16 tools)
  s3_client.py          # Cliente MinIO/S3
  sigtap_client.py      # Leitor SIGTAP (Parquet)
  cnes_client.py        # Leitor CNES (Parquet)
  consulta_manual.py    # Consulta interativa + /explicar
  extrair_manual.py     # Extração multi-formato
  indexar_manual.py     # Indexação vetorial
  validar_critica.py    # Código vs manual (sem IA)
  analisar_critica.py   # Agente de análise crítica (com IA)
  mapear_criticas.py    # Referência cruzada em lote
  setup.sh              # Setup automatizado
  .env.example          # Variáveis de ambiente
```
