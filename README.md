# Manual RAG — Auditoria de Faturamento SIH/SUS

Sistema RAG (Retrieval-Augmented Generation) para auditoria de faturamento hospitalar SIH/SUS com consulta de manuais, portarias, SIGTAP e CNES em linguagem natural.

Funciona como **MCP Server** para o Claude Code, expondo **43 tools** organizadas em 8 módulos: RAG, SIGTAP, CNES, auditoria, auditoria de AIH, inteligência, legacy e health.

**v2.1.0** — Busca híbrida (semântica + BM25), DuckDB/DATASUS client, Docker Compose, parent-child chunking.

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
python scripts/indexar_manual.py
```

### 3. Registrar MCP no Claude Code

```bash
# Local (este repo)
claude mcp add manual-sih -- .venv/bin/python mcp_server.py

# Global (qualquer repo)
pip install -e .
claude mcp add --scope user manual-sih -- manual-sih-mcp
```

Abra uma nova sessão do Claude Code — as 43 tools ficam disponíveis automaticamente.

### 4. SIGTAP e CNES via DATASUS

As tools de SIGTAP e CNES usam DuckDB sobre Parquet armazenado no MinIO. Precisa do container do `modulo-processos` rodando:

```bash
cd modulo-processos && docker compose up -d minio
```

Copie `.env.example` para `.env` e ajuste se necessário:

```bash
cp .env.example .env
```

Variáveis relevantes:

| Variável | Default | Descrição |
|----------|---------|-----------|
| `S3_ENDPOINT` | `http://localhost:9000` | Endpoint MinIO/S3 |
| `AWS_ACCESS_KEY_ID` | `minioadmin` | Credencial S3 |
| `AWS_SECRET_ACCESS_KEY` | `minioadmin` | Credencial S3 |
| `DATASUS_BUCKET` | `bucket-datasus` | Bucket com Parquets SIGTAP/CNES |
| `CHROMA_HOST` | `localhost` | Host ChromaDB (para modo Docker) |
| `CHROMA_PORT` | `8000` | Porta ChromaDB |
| `MCP_HOST` | `0.0.0.0` | Host do MCP Server (modo SSE) |
| `MCP_PORT` | `8200` | Porta do MCP Server (modo SSE) |
| `LOG_LEVEL` | `WARNING` | Nível de log |

### 5. Docker Compose (opcional)

Para rodar o MCP Server e ChromaDB em containers:

```bash
docker compose up -d
```

Expõe o MCP Server na porta `8200` e ChromaDB na `8201`.

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
python scripts/indexar_manual.py
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
python scripts/indexar_manual.py
```

A indexação gera embeddings (paraphrase-multilingual-MiniLM-L12-v2) no ChromaDB e um índice BM25 para busca híbrida.

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
python scripts/mapear_criticas.py
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

Gera parent-child chunks em `data/chunks.json`.

### `indexar_manual.py` — Indexação vetorial + BM25

Gera embeddings e indexa no ChromaDB. Constrói índice BM25 para busca híbrida. Deve ser executado após cada `extrair_manual.py`.

```bash
python scripts/indexar_manual.py
```

## MCP Tools (43)

### RAG — Busca no manual (10 tools)

| Tool | Descrição |
|------|-----------|
| `buscar_manual` | Busca semântica no manual SIH/SUS |
| `buscar_critica` | Busca crítica por número |
| `listar_criticas` | Lista críticas com filtro |
| `buscar_por_secao` | Busca seção por número |
| `verificar_citacao` | Verifica se seção existe antes de citá-la |
| `extrair_dados_aih` | Extrai dados de espelho de AIH (texto livre) |
| `ler_codigo_critica` | Lê código TypeScript da crítica |
| `contexto_critica` | Contexto completo: código + manual + mapeamento |
| `listar_fontes` | Fontes indexadas no banco com tipo e ano |
| `listar_secoes` | Seções do manual |

### SIGTAP — Procedimentos SUS (13 tools)

| Tool | Descrição |
|------|-----------|
| `consultar_procedimento` | Procedimento SIGTAP por código (legacy) |
| `buscar_procedimento` | Busca SIGTAP por nome (legacy) |
| `info_sigtap` | Metadata do SIGTAP carregado |
| `consultar_procedimento_completo` | Procedimento com todas as tabelas relacionadas |
| `buscar_cid` | Busca CID por nome |
| `consultar_cid` | CID por código |
| `listar_cids_procedimento` | CIDs compatíveis com um procedimento |
| `listar_compatibilidades` | Compatibilidades de um procedimento |
| `consultar_habilitacoes_procedimento` | Habilitações exigidas por procedimento |
| `consultar_servicos_procedimento` | Serviços/classificações exigidos |
| `consultar_ocupacoes_procedimento` | Ocupações (CBO) permitidas |
| `consultar_leitos_procedimento` | Tipos de leito compatíveis |
| `consultar_incrementos` | Incrementos financeiros aplicáveis |

### SIGTAP — Hierarquia e regras (3 tools)

| Tool | Descrição |
|------|-----------|
| `consultar_hierarquia_sigtap` | Grupo/subgrupo/forma de organização |
| `consultar_descricao_procedimento` | Descrição detalhada do procedimento |
| `consultar_regras_condicionadas` | Regras condicionadas do procedimento |

### CNES — Estabelecimentos (8 tools)

| Tool | Descrição |
|------|-----------|
| `consultar_cnes` | Dados operacionais de um CNES (legacy) |
| `buscar_profissionais_cnes` | Profissionais de um CNES (legacy) |
| `info_cnes` | Metadata do CNES carregado |
| `consultar_cnes_completo` | CNES com leitos, serviços, habilitações e equipes |
| `consultar_leitos_cnes_detalhado` | Leitos de um CNES com SUS/não-SUS |
| `consultar_servicos_cnes_detalhado` | Serviços/classificações de um CNES |
| `consultar_habilitacoes_cnes_detalhado` | Habilitações de um CNES |
| `buscar_profissionais_detalhado` | Profissionais com CBO, carga horária, vínculos |

### CNES — Profissionais (1 tool)

| Tool | Descrição |
|------|-----------|
| `consultar_dados_profissional` | Dados de profissional por CNS/CPF |

### Auditoria (3 tools)

| Tool | Descrição |
|------|-----------|
| `validar_procedimento_cnes` | Valida procedimento vs capacidade do CNES |
| `validar_cid_procedimento` | Valida compatibilidade CID x procedimento |
| `perfil_auditoria` | Perfil completo do CNES para auditoria |

### Auditoria de AIH (2 tools)

| Tool | Descrição |
|------|-----------|
| `auditar_aih` | Auditoria completa: procedimento + CID + CNES + profissional |
| `calcular_valor_aih` | Calcula valor da AIH com incrementos |

### Inteligência (2 tools)

| Tool | Descrição |
|------|-----------|
| `sugerir_procedimentos_por_cid` | Sugere procedimentos a partir de um CID |
| `comparar_procedimento_competencias` | Compara procedimento entre competências SIGTAP |

### Health (2 tools)

| Tool | Descrição |
|------|-----------|
| `health_check` | Status de todos os subsistemas (RAG, DATASUS, etc.) |
| `info_servidor` | Versão, tools registradas e configuração |

## Entry points

| Comando | Descrição |
|---------|-----------|
| `manual-sih` | Consulta interativa (CLI) |
| `manual-sih-mcp` | MCP Server modo stdio (para Claude Code) |
| `manual-sih-server` | MCP Server modo SSE (servidor compartilhado) |

## Estrutura

```
scripts/manual-rag/
  src/manual_sih_rag/       # Pacote principal
    config.py               # Configuração centralizada (env vars)
    rag/                    # Motor RAG
      engine.py             #   Carregar sistema (model + collection)
      hybrid_search.py      #   Busca híbrida semântica + BM25
      search_primitives.py  #   Tokenização e primitivas de busca
      aih_parser.py         #   Parser de espelhos de AIH
      hints.py              #   Hints de busca por tipo
      paths.py              #   Caminhos do projeto
    datasus/                # Client DATASUS (DuckDB + S3/MinIO)
      client.py             #   Client principal com connection pool
      connection.py         #   Gerenciamento de conexões DuckDB
      cache.py              #   Cache de queries
      metrics.py            #   Métricas de uso
      schemas.py            #   Schemas de dados
      sigtap/               #   Namespace SIGTAP (resources + types)
      cnes/                 #   Namespace CNES (resources + types)
    tools/                  # MCP Tools (43 tools em 8 módulos)
      rag_tools.py          #   10 tools de busca no manual
      sigtap_tools.py       #   13 tools SIGTAP completo
      cnes_tools.py         #   6 tools CNES detalhado
      auditoria_tools.py    #   3 tools de auditoria
      auditoria_aih_tools.py #  2 tools de auditoria de AIH
      inteligencia_tools.py #   2 tools de inteligência
      legacy_tools.py       #   6 tools legacy (SIGTAP/CNES básico)
      health_tools.py       #   2 tools de health check
    criticas/               # Leitura e análise de críticas
    extraction/             # Extração multi-formato (PDF, HTML, DOC, ZIP)
    validation/             # Validação de respostas
    shared/                 # Utilitários (log, erros, normalização)
    legacy/                 # Clients legados (s3, sigtap, cnes)
  scripts/
    indexar_manual.py       # Indexação vetorial + BM25
    mapear_criticas.py      # Referência cruzada em lote
    agente.py               # Agente de análise
    avaliar_rag.py          # Avaliação de qualidade do RAG
  ragData/
    manuais/                # PDFs dos manuais SIH/SUS e SIA/SUS
    portarias/              # Portarias (PDF, HTML, DOC, ZIP)
  data/
    chunks.json             # Chunks extraídos (parent + child)
    bm25_index.pkl          # Índice BM25 para busca híbrida
    secoes.json             # Seções detectadas
    analises/               # Pareceres do agente
  db/                       # Banco vetorial ChromaDB
  mcp_server.py             # MCP Server (43 tools, 8 módulos)
  consulta_manual.py        # Consulta interativa + /explicar
  extrair_manual.py         # Extração multi-formato
  validar_critica.py        # Código vs manual (sem IA)
  analisar_critica.py       # Agente de análise crítica (com IA)
  busca_hibrida.py          # Busca híbrida standalone
  validar_resposta.py       # Validação de respostas
  docker-compose.yml        # MCP Server + ChromaDB containerizados
  Dockerfile                # Build do MCP Server
  pyproject.toml            # Dependências e entry points
  setup.sh                  # Setup automatizado
```
