"""
Sistema de consulta RAG para o Manual Tecnico SIH/SUS.
Permite fazer perguntas em linguagem natural e recebe trechos relevantes do manual.

Comandos especiais:
  /explicar <N>    - Explica como a critica N e validada (usa Gemini + RAG)
  /aih             - Colar espelho de AIH e buscar regras relevantes no manual
  /aih analise     - Colar espelho de AIH e analisar com IA (Gemini)
  /critica         - Modo validacao de criticas (busca semantica)
"""

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

# Re-exports from package (backward compat)
from manual_sih_rag.rag import (  # noqa: F401
    CRITICA_HINTS,
    GRUPO_SIGTAP,
    buscar,
    carregar_sistema,
    extrair_dados_aih,
    ler_texto_multilinhas,
)

console = Console()


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

        titulo = f"[{cor}]#{i+1}[/{cor}] Secao {meta['secao']} - {meta['titulo']} (p.{meta['pagina']}) [{cor}]relevancia: {score:.0%}[/{cor}]"

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
    """Modo especial para validar criticas contra o manual."""
    console.print(
        Panel(
            "Digite o numero ou codigo da critica para ver qual secao do manual a fundamenta.\n"
            "Exemplos: 'critica 7', '050046', 'compatibilidade CID procedimento'",
            title="[bold]Modo Validacao de Criticas[/bold]",
            border_style="cyan",
        )
    )

    while True:
        try:
            entrada = Prompt.ask("\n[bold cyan]Critica[/bold cyan]")
        except (KeyboardInterrupt, EOFError):
            break

        if entrada.lower() in ("sair", "exit", "quit", "q"):
            break

        resultados = buscar(entrada, model, collection, n_resultados=3)
        exibir_resultados(f"Fundamentacao da {entrada}", resultados)


def carregar_api_key() -> str | None:
    """Carrega a API key do Gemini (retorna None se nao disponivel)."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    key_file = Path.home() / ".config" / "google" / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    return None


def modo_explicar_critica(numero: int, model: SentenceTransformer, collection):
    """Explica como uma critica e validada usando Gemini + RAG + codigo."""
    api_key = carregar_api_key()
    if not api_key:
        console.print("[red]API key do Gemini nao encontrada.[/red]")
        console.print("[dim]Configure via GEMINI_API_KEY ou ~/.config/google/api_key[/dim]")
        return

    try:
        from manual_sih_rag.criticas.validar import (
            buscar_manual,
            extrair_logica_hasCritica,
            extrair_termos_busca,
            ler_codigo_critica,
            ler_definicao_critica,
        )
    except ImportError:
        console.print("[red]Modulo criticas nao encontrado.[/red]")
        return

    definicao = ler_definicao_critica(numero)
    if not definicao:
        console.print(f"[red]Critica {numero} nao encontrada em criticas.ts[/red]")
        return

    codigo = ler_codigo_critica(numero)
    if not codigo:
        console.print(f"[red]Arquivo critica{numero}.ts nao encontrado[/red]")
        return

    console.print(
        Panel(
            f"[bold cyan]{definicao['nome']}[/bold cyan]\n"
            f"Codigo SIH: [bold]{definicao['codigo']}[/bold]",
            title=f"[bold blue]Explicando Critica {numero}[/bold blue]",
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
Explique de forma clara e didatica como funciona a validacao da critica {numero} ({definicao['nome']}) do SIH/SUS.

Estruture assim:
1. **O que essa critica verifica** (em linguagem simples)
2. **Passo a passo da validacao** (como o sistema decide se gera ou nao a critica)
3. **Campos envolvidos** (quais dados da AIH sao verificados)
4. **Excecoes** (casos em que a critica NAO e gerada mesmo quando a condicao e atendida)
5. **Fundamentacao** (o que o manual SIH/SUS diz sobre isso)

## Codigo da critica (TypeScript)
```typescript
{logica}
```

## Trechos do Manual SIH/SUS
{secoes_texto}

Responda em portugues. Seja tecnico mas acessivel.\
"""

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.0-flash",
        config=genai_types.GenerateContentConfig(
            system_instruction="Voce e um especialista em faturamento hospitalar SIH/SUS. Explique regras de validacao de forma clara e tecnica.",
            max_output_tokens=3000,
        ),
    )

    console.print("[dim]Gerando explicacao...[/dim]\n")
    resposta = ""
    for chunk in chat.send_message_stream(prompt):
        if chunk.text:
            resposta += chunk.text
            console.print(chunk.text, end="", highlight=False)
    console.print()

    # Follow-up interativo
    console.print("\n[dim]Pergunte mais sobre esta critica, ou 'sair' para voltar.[/dim]")
    while True:
        try:
            pergunta = Prompt.ask(f"\n[cyan]Critica {numero}[/cyan]")
        except (KeyboardInterrupt, EOFError):
            break
        if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
            break

        console.print()
        for chunk in chat.send_message_stream(pergunta):
            if chunk.text:
                console.print(chunk.text, end="", highlight=False)
        console.print()


def modo_analisar_aih(model, collection, usar_ia: bool = False):
    """Analisa uma AIH colada, buscando regras relevantes no manual."""
    console.print(
        Panel(
            "[bold]Cole o espelho da AIH abaixo.[/bold]\n"
            "Quando terminar, digite [bold cyan]/fim[/bold cyan] em uma nova linha.",
            title="[bold blue]Analise de AIH[/bold blue]",
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

    # Exibir dados extraidos
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
        info_lines.append(f"Carater: {dados['carater']}")
    if dados["motivo_saida"]:
        info_lines.append(f"Motivo Saida: {dados['motivo_saida']}")

    procs = dados["procedimentos_unicos"]
    info_lines.append(f"Procedimentos unicos: [bold]{len(procs)}[/bold]")

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
            f"CIDs secundarios: {', '.join(dados['cids_secundarios'])}"
        )

    console.print(
        Panel(
            "\n".join(info_lines),
            title="[bold cyan]Dados Extraidos[/bold cyan]",
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
        queries.append(f"diagnostico {cid} {nome} compatibilidade procedimento CID")

    if dados["procedimento_principal"] and dados["diagnostico_principal"]:
        _, nome_proc = dados["procedimento_principal"]
        cid, nome_diag = dados["diagnostico_principal"]
        queries.append(f"compatibilidade {nome_proc} com {cid} {nome_diag}")

    if dados["especialidade"]:
        queries.append(
            f"especialidade {dados['especialidade']} AIH regras validacao internacao"
        )

    if dados["carater"]:
        queries.append(f"carater atendimento {dados['carater']} AIH regras")

    if dados["motivo_saida"]:
        queries.append(f"motivo saida {dados['motivo_saida']} AIH regras")

    for g in sorted(grupos):
        nome_g = GRUPO_SIGTAP.get(g, f"grupo {g}")
        queries.append(
            f"procedimentos {nome_g} grupo {g} SIGTAP AIH regras quantidade limite"
        )

    if dados["cids_secundarios"]:
        queries.append(
            f"CID secundario {' '.join(dados['cids_secundarios'][:4])} "
            "causas externas politraumatismo"
        )

    console.print(f"\n[dim]Executando {len(queries)} buscas no manual...[/dim]\n")

    vistos = set()
    todos_resultados = []

    for q in queries:
        resultados = buscar(q, model, collection, n_resultados=3)
        for r in resultados:
            if r["id"] not in vistos:
                vistos.add(r["id"])
                todos_resultados.append((q, r))

    todos_resultados.sort(key=lambda x: x[1]["score"], reverse=True)

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
            f"(p.{meta['pagina']}) [{cor}]relevancia: {score:.0%}[/{cor}]"
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

    if usar_ia:
        _analisar_aih_com_ia(dados, todos_resultados)

    console.print(
        "\n[dim]Faca perguntas sobre esta AIH, ou 'sair' para voltar.[/dim]"
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
    """Analisa a AIH com Gemini usando os dados extraidos + trechos do manual."""
    api_key = carregar_api_key()
    if not api_key:
        console.print(
            "[yellow]API key nao disponivel. Pulando analise por IA.[/yellow]"
        )
        return

    from google import genai
    from google.genai import types as genai_types

    info = []
    if dados["procedimento_principal"]:
        cod, nome = dados["procedimento_principal"]
        info.append(f"Procedimento Principal: {cod} - {nome}")
    if dados["diagnostico_principal"]:
        cid, nome = dados["diagnostico_principal"]
        info.append(f"Diagnostico Principal: {cid} - {nome}")
    if dados["especialidade"]:
        info.append(f"Especialidade: {dados['especialidade']}")
    if dados["carater"]:
        info.append(f"Carater: {dados['carater']}")
    if dados["motivo_saida"]:
        info.append(f"Motivo Saida: {dados['motivo_saida']}")
    info.append(f"Procedimentos: {', '.join(dados['procedimentos_unicos'])}")
    if dados["cids_secundarios"]:
        info.append(f"CIDs Secundarios: {', '.join(dados['cids_secundarios'])}")

    secoes_texto = ""
    for i, (query, r) in enumerate(resultados[:8]):
        meta = r["metadata"]
        secoes_texto += (
            f"\n--- Trecho {i+1}: {meta['secao']} - {meta['titulo']} "
            f"(p.{meta['pagina']}, {r['score']:.0%}) ---\n"
            f"{r['texto']}\n"
        )

    prompt = f"""\
Analise esta AIH e identifique potenciais problemas de validacao (criticas SIH/SUS).

## Dados da AIH
{chr(10).join(info)}

## Trechos relevantes do Manual SIH/SUS
{secoes_texto}

Identifique:
1. **Compatibilidades** - procedimento x diagnostico, procedimento x sexo, procedimento x idade
2. **Quantidades** - limites de quantidade por procedimento
3. **Regras de permanencia** - diarias, UTI, mudanca de procedimento
4. **OPM** - compatibilidade de materiais com procedimento cirurgico
5. **Outros** - qualquer regra relevante que possa gerar critica

Seja especifico sobre quais criticas poderiam ser geradas e por que.
Responda em portugues.\
"""

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.0-flash",
        config=genai_types.GenerateContentConfig(
            system_instruction="Voce e um especialista em faturamento hospitalar SIH/SUS. "
            "Analise AIHs e identifique potenciais problemas de validacao.",
            max_output_tokens=4000,
        ),
    )

    console.print("\n[dim]Analisando AIH com IA...[/dim]\n")
    for chunk in chat.send_message_stream(prompt):
        if chunk.text:
            console.print(chunk.text, end="", highlight=False)
    console.print()

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

        console.print()
        for chunk in chat.send_message_stream(pergunta):
            if chunk.text:
                console.print(chunk.text, end="", highlight=False)
        console.print()


def modo_interativo(model: SentenceTransformer, collection):
    """Modo de consulta interativa."""
    console.print(
        Panel(
            "[bold]Comandos disponiveis:[/bold]\n\n"
            "  [cyan]<pergunta>[/cyan]       - Buscar no manual (ex: 'como registrar politraumatizado')\n"
            "  [cyan]/explicar N[/cyan]      - Explicar como a critica N e validada (usa IA)\n"
            "  [cyan]/aih[/cyan]             - Colar espelho de AIH e buscar regras relevantes\n"
            "  [cyan]/aih analise[/cyan]     - Colar espelho de AIH e analisar com IA\n"
            "  [cyan]/critica[/cyan]         - Modo validacao de criticas (busca semantica)\n"
            "  [cyan]/secoes[/cyan]          - Listar todas as secoes do manual\n"
            "  [cyan]/fontes[/cyan]          - Listar todas as fontes indexadas\n"
            "  [cyan]/buscar N[/cyan]        - Alterar quantidade de resultados (padrao: 5)\n"
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
                console.print("[red]Uso: /explicar <numero da critica>[/red]")
                continue
            try:
                num = int(partes[1])
            except ValueError:
                console.print("[red]Numero invalido. Uso: /explicar 92[/red]")
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
            todos = collection.get(include=["metadatas"])
            secoes_vistas = {}
            for meta in todos["metadatas"]:
                key = meta["secao"]
                if key not in secoes_vistas:
                    secoes_vistas[key] = meta

            table = Table(title="Secoes do Manual SIH/SUS")
            table.add_column("Secao", style="cyan")
            table.add_column("Titulo", style="white")
            table.add_column("Pagina", style="dim")

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
                console.print("[red]Uso: /buscar <numero>[/red]")
            continue

        resultados = buscar(pergunta, model, collection, n_resultados)
        exibir_resultados(pergunta, resultados)


def consulta_unica(pergunta: str, model: SentenceTransformer, collection):
    """Faz uma consulta e retorna (para uso programatico)."""
    resultados = buscar(pergunta, model, collection, n_resultados=5)
    exibir_resultados(pergunta, resultados)


def main():
    console.print(
        "\n[bold blue]Manual SIH/SUS - Sistema de Consulta RAG[/bold blue]\n"
    )

    model, collection = carregar_sistema()

    if len(sys.argv) > 1:
        pergunta = " ".join(sys.argv[1:])
        consulta_unica(pergunta, model, collection)
    else:
        modo_interativo(model, collection)

    console.print("\n[dim]Ate logo![/dim]")


if __name__ == "__main__":
    main()
