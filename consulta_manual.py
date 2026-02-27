"""
Sistema de consulta RAG para o Manual Técnico SIH/SUS.
Permite fazer perguntas em linguagem natural e recebe trechos relevantes do manual.

Comandos especiais:
  /explicar <N>    - Explica como a crítica N é validada (usa Gemini + RAG)
  /aih             - Colar espelho de AIH e buscar regras relevantes no manual
  /aih analise     - Colar espelho de AIH e analisar com IA (Gemini)
  /critica         - Modo validação de críticas (busca semântica)
"""

import io
import os
import re
import sys
from pathlib import Path

import chromadb
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from sentence_transformers import SentenceTransformer

console = Console()

# Mapeamento de críticas para termos de busca (exemplos comuns)
CRITICA_HINTS = {
    "critica 7": "procedimento principal incompatível com diagnóstico principal CID compatibilidade",
    "critica 12": "diagnóstico principal incompatível com sexo do paciente",
    "critica 13": "procedimento principal incompatível com idade do paciente",
    "critica 14": "sexo do paciente incompatível com procedimento principal",
    "critica 15": "procedimento principal não permite permanência",
    "050009": "número da AIH não informado",
    "050046": "procedimento principal incompatível com diagnóstico principal",
    "050081": "diagnóstico principal incompatível com sexo",
    "050083": "procedimento incompatível com idade",
    "050084": "sexo incompatível com procedimento",
    "050097": "procedimento não permite permanência",
}


def carregar_sistema():
    """Carrega modelo e banco vetorial (com busca híbrida se disponível)."""
    db_dir = Path(__file__).parent / "db"

    if not db_dir.exists():
        console.print(
            "[red]Erro: Banco vetorial não encontrado. Execute primeiro:[/red]"
        )
        console.print("  python extrair_manual.py")
        console.print("  python indexar_manual.py")
        sys.exit(1)

    # Tentar sistema híbrido primeiro
    try:
        from busca_hibrida import carregar_sistema_hibrido
        console.print("[dim]Carregando sistema de busca híbrida...[/dim]")
        model, collection = carregar_sistema_hibrido()
        console.print(
            f"[green]Sistema híbrido pronto! {collection.count()} trechos indexados.[/green]\n"
        )
        return model, collection
    except (ImportError, Exception):
        pass

    # Fallback: sistema original
    console.print("[dim]Carregando modelo de embeddings...[/dim]")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    console.print("[dim]Conectando ao banco vetorial...[/dim]")
    chroma_host = os.getenv("CHROMA_HOST")
    if chroma_host:
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    else:
        client = chromadb.PersistentClient(path=str(db_dir))
    collection = client.get_collection("manual_sih")

    console.print(
        f"[green]Sistema pronto! {collection.count()} trechos indexados.[/green]\n"
    )
    return model, collection


def buscar(
    pergunta: str,
    model: SentenceTransformer,
    collection,
    n_resultados: int = 5,
) -> list[dict]:
    """Busca trechos relevantes do manual para a pergunta."""
    # Usar busca híbrida se disponível
    try:
        from busca_hibrida import buscar_hibrida, _bm25
        if _bm25 is not None:
            return buscar_hibrida(pergunta, model, collection, n_resultados)
    except (ImportError, Exception):
        pass

    # Fallback: busca vetorial original
    pergunta_lower = pergunta.lower().strip()
    for chave, hint in CRITICA_HINTS.items():
        if chave in pergunta_lower:
            pergunta = f"{pergunta} {hint}"
            break

    embedding = model.encode([pergunta], normalize_embeddings=True)

    resultados = collection.query(
        query_embeddings=[embedding[0].tolist()],
        n_results=n_resultados,
        include=["documents", "metadatas", "distances"],
    )

    items = []
    for i in range(len(resultados["ids"][0])):
        items.append(
            {
                "id": resultados["ids"][0][i],
                "texto": resultados["documents"][0][i],
                "metadata": resultados["metadatas"][0][i],
                "score": 1 - resultados["distances"][0][i],
            }
        )

    return items


def exibir_resultados(pergunta: str, resultados: list[dict]):
    """Exibe os resultados formatados no terminal."""
    console.print(f"\n[bold cyan]Pergunta:[/bold cyan] {pergunta}\n")

    if not resultados:
        console.print("[yellow]Nenhum resultado encontrado.[/yellow]")
        return

    for i, r in enumerate(resultados):
        meta = r["metadata"]
        score = r["score"]
        cor = "green" if score > 0.5 else "yellow" if score > 0.3 else "red"

        titulo = f"[{cor}]#{i+1}[/{cor}] Seção {meta['secao']} - {meta['titulo']} (p.{meta['pagina']}) [{cor}]relevância: {score:.0%}[/{cor}]"

        console.print(
            Panel(
                r["texto"],
                title=titulo,
                border_style=cor,
                padding=(1, 2),
            )
        )


def modo_validar_critica(
    model: SentenceTransformer, collection
):
    """Modo especial para validar críticas contra o manual."""
    console.print(
        Panel(
            "Digite o número ou código da crítica para ver qual seção do manual a fundamenta.\n"
            "Exemplos: 'critica 7', '050046', 'compatibilidade CID procedimento'",
            title="[bold]Modo Validação de Críticas[/bold]",
            border_style="cyan",
        )
    )

    while True:
        try:
            entrada = Prompt.ask("\n[bold cyan]Crítica[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            break

        if entrada.lower() in ("sair", "exit", "quit", "q"):
            break

        resultados = buscar(entrada, model, collection, n_resultados=3)
        exibir_resultados(f"Fundamentação da {entrada}", resultados)


def carregar_api_key() -> str | None:
    """Carrega a API key do Gemini (retorna None se não disponível)."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    key_file = Path.home() / ".config" / "google" / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    return None


def modo_explicar_critica(numero: int, model: SentenceTransformer, collection):
    """Explica como uma crítica é validada usando Gemini + RAG + código."""
    api_key = carregar_api_key()
    if not api_key:
        console.print("[red]API key do Gemini não encontrada.[/red]")
        console.print("[dim]Configure via GEMINI_API_KEY ou ~/.config/google/api_key[/dim]")
        return

    try:
        from validar_critica import (
            buscar_manual,
            extrair_logica_hasCritica,
            extrair_termos_busca,
            ler_codigo_critica,
            ler_definicao_critica,
        )
    except ImportError:
        console.print("[red]validar_critica.py não encontrado no mesmo diretório.[/red]")
        return

    definicao = ler_definicao_critica(numero)
    if not definicao:
        console.print(f"[red]Crítica {numero} não encontrada em criticas.ts[/red]")
        return

    codigo = ler_codigo_critica(numero)
    if not codigo:
        console.print(f"[red]Arquivo critica{numero}.ts não encontrado[/red]")
        return

    console.print(
        Panel(
            f"[bold cyan]{definicao['nome']}[/bold cyan]\n"
            f"Código SIH: [bold]{definicao['codigo']}[/bold]",
            title=f"[bold blue]Explicando Crítica {numero}[/bold blue]",
            border_style="blue",
        )
    )

    console.print("[dim]Buscando contexto no manual...[/dim]")
    queries = extrair_termos_busca(codigo, definicao["nome"])
    secoes = buscar_manual(queries, model, collection, n_por_query=3)

    logica = extrair_logica_hasCritica(codigo)
    secoes_texto = ""
    for i, s in enumerate(secoes[:5]):
        secoes_texto += (
            f"\n--- Trecho {i+1}: {s['titulo']} (p.{s['pagina']}, {s['relevancia']:.0%}) ---\n"
            f"{s['texto']}\n"
        )

    prompt = f"""\
Explique de forma clara e didática como funciona a validação da crítica {numero} ({definicao['nome']}) do SIH/SUS.

Estruture assim:
1. **O que essa crítica verifica** (em linguagem simples)
2. **Passo a passo da validação** (como o sistema decide se gera ou não a crítica)
3. **Campos envolvidos** (quais dados da AIH são verificados)
4. **Exceções** (casos em que a crítica NÃO é gerada mesmo quando a condição é atendida)
5. **Fundamentação** (o que o manual SIH/SUS diz sobre isso)

## Código da crítica (TypeScript)
```typescript
{logica}
```

## Trechos do Manual SIH/SUS
{secoes_texto}

Responda em português. Seja técnico mas acessível.\
"""

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.0-flash",
        config=genai_types.GenerateContentConfig(
            system_instruction="Você é um especialista em faturamento hospitalar SIH/SUS. Explique regras de validação de forma clara e técnica.",
            max_output_tokens=3000,
        ),
    )

    console.print("[dim]Gerando explicação...[/dim]\n")
    resposta = ""
    for chunk in chat.send_message_stream(prompt):
        if chunk.text:
            resposta += chunk.text
            console.print(chunk.text, end="", highlight=False)
    console.print()

    # Follow-up interativo
    console.print("\n[dim]Pergunte mais sobre esta crítica, ou 'sair' para voltar.[/dim]")
    while True:
        try:
            pergunta = Prompt.ask(f"\n[cyan]Crítica {numero}[/cyan]")
        except (KeyboardInterrupt, EOFError):
            break
        if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
            break

        resposta_fu = ""
        console.print()
        for chunk in chat.send_message_stream(pergunta):
            if chunk.text:
                resposta_fu += chunk.text
                console.print(chunk.text, end="", highlight=False)
        console.print()


GRUPO_SIGTAP = {
    "01": "ações de promoção e prevenção",
    "02": "procedimentos diagnósticos (exames)",
    "03": "procedimentos clínicos (consultas, fisioterapia)",
    "04": "procedimentos cirúrgicos",
    "05": "transplantes de órgãos tecidos e células",
    "06": "medicamentos",
    "07": "órteses próteses e materiais especiais (OPM)",
    "08": "ações complementares (UTI, diárias)",
}


def ler_texto_multilinhas() -> str:
    """Lê entrada multilinha até o usuário digitar /fim."""
    console.print(
        "[dim]Cole o espelho da AIH. Quando terminar, digite "
        "[bold]/fim[/bold] em uma nova linha.[/dim]"
    )
    linhas = []
    while True:
        try:
            linha = input()
            if linha.strip().lower() == "/fim":
                break
            linhas.append(linha)
        except (EOFError, KeyboardInterrupt):
            break
    return "\n".join(linhas)


def extrair_dados_aih(texto: str) -> dict:
    """Extrai dados estruturados de um espelho de AIH colado."""
    dados = {
        "num_aih": None,
        "procedimento_principal": None,
        "diagnostico_principal": None,
        "cids_secundarios": [],
        "procedimentos_unicos": [],
        "especialidade": None,
        "carater": None,
        "motivo_saida": None,
        "tipo": None,
    }

    # Num AIH
    m = re.search(r"Num\s+AIH\s*:\s*([\d-]+)", texto)
    if m:
        dados["num_aih"] = m.group(1).strip()

    # Tipo
    m = re.search(r"Tipo\s*:\s*\d+-(\S+)", texto)
    if m:
        dados["tipo"] = m.group(1).strip()

    # Procedimento principal: XX.XX.XX.XXX-X - NOME
    m = re.search(
        r"[Pp]rocedimento\s+principal\s*:\s*([\d.]+\d-\d)\s*-\s*(.+)", texto
    )
    if m:
        codigo = re.sub(r"[.\-]", "", m.group(1))
        dados["procedimento_principal"] = (codigo, m.group(2).strip())

    # Diagnóstico principal
    m = re.search(r"[Dd]iag\.\s*principal\s*:\s*([A-Z]\d{2,4})\s*-?\s*(.*)", texto)
    if m:
        dados["diagnostico_principal"] = (m.group(1), m.group(2).strip())

    # Especialidade
    m = re.search(r"[Ee]specialidade\s*:\s*\d+\s*-\s*(.+)", texto)
    if m:
        dados["especialidade"] = m.group(1).strip()

    # Caráter atendimento
    m = re.search(r"[Cc]arater\s+atendimento\s*:\s*\d+\s*-\s*(.+)", texto)
    if m:
        dados["carater"] = m.group(1).strip()

    # Motivo saída
    m = re.search(r"[Mm]ot\s*saida\s*:\s*\d+\s*-\s*(.+)", texto)
    if m:
        dados["motivo_saida"] = m.group(1).strip()

    # Procedimentos realizados (10 dígitos começando com 0)
    procs_vistos = set()
    for m in re.finditer(r"\b(0[1-8]\d{8})\b", texto):
        cod = m.group(1)
        if cod not in procs_vistos:
            procs_vistos.add(cod)
            dados["procedimentos_unicos"].append(cod)

    # CIDs secundários - seção específica
    cid_section = re.search(
        r"CID\s+SECUND[ÁA]RIO(.*?)(?:CNPJ\s+Fabricante|MS-DATASUS|$)",
        texto,
        re.DOTALL | re.IGNORECASE,
    )
    if cid_section:
        for m in re.finditer(r"\b([A-Z]\d{3})\b", cid_section.group(1)):
            cid = m.group(1)
            if cid not in dados["cids_secundarios"]:
                dados["cids_secundarios"].append(cid)

    return dados


def modo_analisar_aih(model, collection, usar_ia: bool = False):
    """Analisa uma AIH colada, buscando regras relevantes no manual."""
    console.print(
        Panel(
            "[bold]Cole o espelho da AIH abaixo.[/bold]\n"
            "Quando terminar, digite [bold cyan]/fim[/bold cyan] em uma nova linha.",
            title="[bold blue]Análise de AIH[/bold blue]",
            border_style="blue",
        )
    )

    texto = ler_texto_multilinhas()
    if not texto.strip():
        console.print("[yellow]Nenhum texto colado.[/yellow]")
        return

    console.print(
        f"\n[dim]Texto recebido: {len(texto)} caracteres, "
        f"{len(texto.splitlines())} linhas[/dim]"
    )

    dados = extrair_dados_aih(texto)

    # Exibir dados extraídos
    info_lines = []
    if dados["num_aih"]:
        info_lines.append(f"AIH: [bold]{dados['num_aih']}[/bold]")
    if dados["tipo"]:
        info_lines.append(f"Tipo: {dados['tipo']}")
    if dados["procedimento_principal"]:
        cod, nome = dados["procedimento_principal"]
        info_lines.append(f"Proc. Principal: [bold]{cod}[/bold] - {nome}")
    if dados["diagnostico_principal"]:
        cid, nome = dados["diagnostico_principal"]
        info_lines.append(f"Diag. Principal: [bold]{cid}[/bold] - {nome}")
    if dados["especialidade"]:
        info_lines.append(f"Especialidade: {dados['especialidade']}")
    if dados["carater"]:
        info_lines.append(f"Caráter: {dados['carater']}")
    if dados["motivo_saida"]:
        info_lines.append(f"Motivo Saída: {dados['motivo_saida']}")

    procs = dados["procedimentos_unicos"]
    info_lines.append(f"Procedimentos únicos: [bold]{len(procs)}[/bold]")

    # Agrupar por grupo SIGTAP
    grupos = {}
    for p in procs:
        g = p[:2]
        grupos.setdefault(g, []).append(p)
    for g in sorted(grupos):
        nome_g = GRUPO_SIGTAP.get(g, f"grupo {g}")
        codigos = ", ".join(grupos[g])
        info_lines.append(f"  Grupo {g} ({nome_g}): {codigos}")

    if dados["cids_secundarios"]:
        info_lines.append(
            f"CIDs secundários: {', '.join(dados['cids_secundarios'])}"
        )

    console.print(
        Panel(
            "\n".join(info_lines),
            title="[bold cyan]Dados Extraídos[/bold cyan]",
            border_style="cyan",
        )
    )

    # Construir queries de busca
    queries = []

    if dados["procedimento_principal"]:
        cod, nome = dados["procedimento_principal"]
        queries.append(f"procedimento principal {nome} AIH regras")

    if dados["diagnostico_principal"]:
        cid, nome = dados["diagnostico_principal"]
        queries.append(f"diagnóstico {cid} {nome} compatibilidade procedimento CID")

    if dados["procedimento_principal"] and dados["diagnostico_principal"]:
        _, nome_proc = dados["procedimento_principal"]
        cid, nome_diag = dados["diagnostico_principal"]
        queries.append(f"compatibilidade {nome_proc} com {cid} {nome_diag}")

    if dados["especialidade"]:
        queries.append(
            f"especialidade {dados['especialidade']} AIH regras validação internação"
        )

    if dados["carater"]:
        queries.append(f"caráter atendimento {dados['carater']} AIH regras")

    if dados["motivo_saida"]:
        queries.append(f"motivo saída {dados['motivo_saida']} AIH regras")

    # Buscar por grupos de procedimentos
    for g in sorted(grupos):
        nome_g = GRUPO_SIGTAP.get(g, f"grupo {g}")
        queries.append(
            f"procedimentos {nome_g} grupo {g} SIGTAP AIH regras quantidade limite"
        )

    # CIDs
    if dados["cids_secundarios"]:
        queries.append(
            f"CID secundário {' '.join(dados['cids_secundarios'][:4])} "
            "causas externas politraumatismo"
        )

    console.print(f"\n[dim]Executando {len(queries)} buscas no manual...[/dim]\n")

    # Executar buscas deduplicando resultados
    vistos = set()
    todos_resultados = []

    for q in queries:
        resultados = buscar(q, model, collection, n_resultados=3)
        for r in resultados:
            if r["id"] not in vistos:
                vistos.add(r["id"])
                todos_resultados.append((q, r))

    # Ordenar por relevância
    todos_resultados.sort(key=lambda x: x[1]["score"], reverse=True)

    # Exibir top resultados
    top = todos_resultados[:12]
    console.print(
        f"[bold cyan]Top {len(top)} trechos mais relevantes "
        f"(de {len(todos_resultados)} encontrados):[/bold cyan]\n"
    )

    for i, (query, r) in enumerate(top):
        meta = r["metadata"]
        score = r["score"]
        cor = "green" if score > 0.5 else "yellow" if score > 0.3 else "red"

        titulo = (
            f"[{cor}]#{i+1}[/{cor}] {meta['secao']} - {meta['titulo']} "
            f"(p.{meta['pagina']}) [{cor}]relevância: {score:.0%}[/{cor}]"
        )
        subtitle = f"[dim]Busca: {query[:80]}[/dim]"

        console.print(
            Panel(
                r["texto"],
                title=titulo,
                subtitle=subtitle,
                border_style=cor,
                padding=(1, 2),
            )
        )

    # Se IA habilitada, analisar com Gemini
    if usar_ia:
        _analisar_aih_com_ia(dados, todos_resultados)

    # Modo follow-up
    console.print(
        "\n[dim]Faça perguntas sobre esta AIH, ou 'sair' para voltar.[/dim]"
    )
    while True:
        try:
            pergunta = Prompt.ask("\n[cyan]AIH[/cyan]")
        except (KeyboardInterrupt, EOFError):
            break
        if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
            break

        resultados = buscar(pergunta, model, collection, n_resultados=5)
        exibir_resultados(pergunta, resultados)


def _analisar_aih_com_ia(dados: dict, resultados: list):
    """Analisa a AIH com Gemini usando os dados extraídos + trechos do manual."""
    api_key = carregar_api_key()
    if not api_key:
        console.print(
            "[yellow]API key não disponível. Pulando análise por IA.[/yellow]"
        )
        return

    from google import genai
    from google.genai import types as genai_types

    # Montar contexto
    info = []
    if dados["procedimento_principal"]:
        cod, nome = dados["procedimento_principal"]
        info.append(f"Procedimento Principal: {cod} - {nome}")
    if dados["diagnostico_principal"]:
        cid, nome = dados["diagnostico_principal"]
        info.append(f"Diagnóstico Principal: {cid} - {nome}")
    if dados["especialidade"]:
        info.append(f"Especialidade: {dados['especialidade']}")
    if dados["carater"]:
        info.append(f"Caráter: {dados['carater']}")
    if dados["motivo_saida"]:
        info.append(f"Motivo Saída: {dados['motivo_saida']}")
    info.append(f"Procedimentos: {', '.join(dados['procedimentos_unicos'])}")
    if dados["cids_secundarios"]:
        info.append(f"CIDs Secundários: {', '.join(dados['cids_secundarios'])}")

    secoes_texto = ""
    for i, (query, r) in enumerate(resultados[:8]):
        meta = r["metadata"]
        secoes_texto += (
            f"\n--- Trecho {i+1}: {meta['secao']} - {meta['titulo']} "
            f"(p.{meta['pagina']}, {r['score']:.0%}) ---\n"
            f"{r['texto']}\n"
        )

    prompt = f"""\
Analise esta AIH e identifique potenciais problemas de validação (críticas SIH/SUS).

## Dados da AIH
{chr(10).join(info)}

## Trechos relevantes do Manual SIH/SUS
{secoes_texto}

Identifique:
1. **Compatibilidades** - procedimento x diagnóstico, procedimento x sexo, procedimento x idade
2. **Quantidades** - limites de quantidade por procedimento
3. **Regras de permanência** - diárias, UTI, mudança de procedimento
4. **OPM** - compatibilidade de materiais com procedimento cirúrgico
5. **Outros** - qualquer regra relevante que possa gerar crítica

Seja específico sobre quais críticas poderiam ser geradas e por quê.
Responda em português.\
"""

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.0-flash",
        config=genai_types.GenerateContentConfig(
            system_instruction="Você é um especialista em faturamento hospitalar SIH/SUS. "
            "Analise AIHs e identifique potenciais problemas de validação.",
            max_output_tokens=4000,
        ),
    )

    console.print("\n[dim]Analisando AIH com IA...[/dim]\n")
    resposta = ""
    for chunk in chat.send_message_stream(prompt):
        if chunk.text:
            resposta += chunk.text
            console.print(chunk.text, end="", highlight=False)
    console.print()

    # Follow-up com IA
    console.print(
        "\n[dim]Pergunte mais sobre esta AIH (com IA), ou 'sair' para voltar.[/dim]"
    )
    while True:
        try:
            pergunta = Prompt.ask("\n[cyan]AIH (IA)[/cyan]")
        except (KeyboardInterrupt, EOFError):
            break
        if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
            break

        resposta_fu = ""
        console.print()
        for chunk in chat.send_message_stream(pergunta):
            if chunk.text:
                resposta_fu += chunk.text
                console.print(chunk.text, end="", highlight=False)
        console.print()


def modo_interativo(model: SentenceTransformer, collection):
    """Modo de consulta interativa."""
    console.print(
        Panel(
            "[bold]Comandos disponíveis:[/bold]\n\n"
            "  [cyan]<pergunta>[/cyan]       - Buscar no manual (ex: 'como registrar politraumatizado')\n"
            "  [cyan]/explicar N[/cyan]      - Explicar como a crítica N é validada (usa IA)\n"
            "  [cyan]/aih[/cyan]             - Colar espelho de AIH e buscar regras relevantes\n"
            "  [cyan]/aih analise[/cyan]     - Colar espelho de AIH e analisar com IA\n"
            "  [cyan]/critica[/cyan]         - Modo validação de críticas (busca semântica)\n"
            "  [cyan]/secoes[/cyan]          - Listar todas as seções do manual\n"
            "  [cyan]/fontes[/cyan]          - Listar todas as fontes indexadas\n"
            "  [cyan]/buscar N[/cyan]        - Alterar quantidade de resultados (padrão: 5)\n"
            "  [cyan]sair[/cyan]             - Encerrar\n",
            title="[bold blue]Consulta Manual SIH/SUS[/bold blue]",
            border_style="blue",
        )
    )

    n_resultados = 5

    while True:
        try:
            pergunta = Prompt.ask("\n[bold blue]Manual SIH[/bold blue]")
        except (KeyboardInterrupt, EOFError):
            break

        if not pergunta.strip():
            continue

        if pergunta.lower() in ("sair", "exit", "quit", "q"):
            break

        if pergunta.lower().startswith("/explicar"):
            partes = pergunta.split()
            if len(partes) < 2:
                console.print("[red]Uso: /explicar <número da crítica>[/red]")
                continue
            try:
                num = int(partes[1])
            except ValueError:
                console.print("[red]Número inválido. Uso: /explicar 92[/red]")
                continue
            modo_explicar_critica(num, model, collection)
            continue

        if pergunta.lower().startswith("/aih"):
            usar_ia = "analise" in pergunta.lower()
            modo_analisar_aih(model, collection, usar_ia=usar_ia)
            continue

        if pergunta.lower() == "/critica":
            modo_validar_critica(model, collection)
            continue

        if pergunta.lower() == "/fontes":
            todos = collection.get(include=["metadatas"])
            fontes = {}
            for meta in todos["metadatas"]:
                fonte = meta.get("fonte", "?")
                fontes[fonte] = fontes.get(fonte, 0) + 1

            table = Table(title="Fontes Indexadas")
            table.add_column("Fonte", style="cyan")
            table.add_column("Chunks", style="white", justify="right")
            table.add_column("Tipo", style="dim")
            table.add_column("Ano", style="dim")

            # Agrupar por fonte com metadados do primeiro chunk
            fonte_meta = {}
            for meta in todos["metadatas"]:
                f = meta.get("fonte", "?")
                if f not in fonte_meta:
                    fonte_meta[f] = meta

            for fonte in sorted(fontes.keys()):
                meta = fonte_meta.get(fonte, {})
                table.add_row(
                    fonte,
                    str(fontes[fonte]),
                    meta.get("tipo", "?"),
                    meta.get("ano", "?"),
                )

            console.print(table)
            continue

        if pergunta.lower() == "/secoes":
            # Buscar todas as seções únicas
            todos = collection.get(include=["metadatas"])
            secoes_vistas = {}
            for meta in todos["metadatas"]:
                key = meta["secao"]
                if key not in secoes_vistas:
                    secoes_vistas[key] = meta

            table = Table(title="Seções do Manual SIH/SUS")
            table.add_column("Seção", style="cyan")
            table.add_column("Título", style="white")
            table.add_column("Página", style="dim")

            for key in sorted(
                secoes_vistas.keys(), key=lambda x: [int(p) for p in x.split(".")]
            ):
                meta = secoes_vistas[key]
                table.add_row(meta["secao"], meta["titulo"], str(meta["pagina"]))

            console.print(table)
            continue

        if pergunta.lower().startswith("/buscar "):
            try:
                n_resultados = int(pergunta.split()[1])
                console.print(
                    f"[dim]Quantidade de resultados alterada para {n_resultados}[/dim]"
                )
            except (ValueError, IndexError):
                console.print("[red]Uso: /buscar <número>[/red]")
            continue

        resultados = buscar(pergunta, model, collection, n_resultados)
        exibir_resultados(pergunta, resultados)


def consulta_unica(pergunta: str, model: SentenceTransformer, collection):
    """Faz uma consulta e retorna (para uso programático)."""
    resultados = buscar(pergunta, model, collection, n_resultados=5)
    exibir_resultados(pergunta, resultados)


def main():
    console.print(
        "\n[bold blue]Manual SIH/SUS - Sistema de Consulta RAG[/bold blue]\n"
    )

    model, collection = carregar_sistema()

    if len(sys.argv) > 1:
        # Modo consulta única via linha de comando
        pergunta = " ".join(sys.argv[1:])
        consulta_unica(pergunta, model, collection)
    else:
        # Modo interativo
        modo_interativo(model, collection)

    console.print("\n[dim]Até logo![/dim]")


if __name__ == "__main__":
    main()
