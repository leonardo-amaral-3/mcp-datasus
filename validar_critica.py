"""
Valida uma critica mostrando:
  1. RESUMO em portugues do que o codigo faz (lido do .ts real)
  2. SECOES do manual que fundamentam essa regra
  3. Modo interativo para perguntar sobre a critica

Uso:
  python validar_critica.py 129
  python validar_critica.py 7
"""

import io
import os
import sys
from pathlib import Path

import chromadb
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from sentence_transformers import SentenceTransformer

# Re-exports from package (backward compat)
from manual_sih_rag.criticas.validar import (  # noqa: F401
    buscar_manual,
    extrair_logica_hasCritica,
    extrair_termos_busca,
    ler_codigo_critica,
    ler_definicao_critica,
    listar_arquivos_critica,
)
from manual_sih_rag.criticas.paths import (  # noqa: F401
    CRITICAS_DIR,
    CRITICAS_TS,
    PROJETO_DIR,
)

console = Console()


def main():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    if len(sys.argv) < 2:
        console.print("[bold]Uso:[/bold] python validar_critica.py <numero_critica>")
        console.print("  Ex: python validar_critica.py 129")
        sys.exit(0)

    numero = int(sys.argv[1])

    # Carregar
    console.print("[dim]Carregando...[/dim]")
    old = sys.stderr
    sys.stderr = io.StringIO()
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    client = chromadb.PersistentClient(path=str(Path(__file__).parent / "db"))
    collection = client.get_collection("manual_sih")
    sys.stderr = old

    # Ler critica
    definicao = ler_definicao_critica(numero)
    if not definicao:
        console.print(f"[red]Critica {numero} nao encontrada em criticas.ts[/red]")
        sys.exit(1)

    codigo = ler_codigo_critica(numero)
    if not codigo:
        console.print(f"[red]Arquivo critica{numero}.ts nao encontrado[/red]")
        sys.exit(1)

    # ==================== HEADER ====================
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{definicao['nome']}[/bold cyan]\n"
            f"Codigo SIH: [bold]{definicao['codigo']}[/bold]  |  Campos: {', '.join(definicao['campos'])}",
            title=f"[bold blue]Critica {numero}[/bold blue]",
            border_style="blue",
        )
    )

    # ==================== 1. CODIGO ====================
    console.print("\n[bold yellow]1. O QUE O CODIGO FAZ[/bold yellow]")
    console.print(f"[dim]Arquivo: processos-criticas/src/criticas/critica{numero}/critica{numero}.ts[/dim]\n")

    logica = extrair_logica_hasCritica(codigo)
    console.print(
        Syntax(logica, "typescript", theme="monokai", line_numbers=False, word_wrap=True)
    )

    arquivos = listar_arquivos_critica(numero)
    if len(arquivos) > 1:
        console.print(f"\n[dim]Arquivos relacionados: {', '.join(arquivos)}[/dim]")

    # ==================== 2. MANUAL ====================
    console.print("\n[bold yellow]2. O QUE O MANUAL DIZ[/bold yellow]")

    queries = extrair_termos_busca(codigo, definicao["nome"])
    console.print(f"[dim]Buscando por: {' | '.join(q[:50] for q in queries[:4])}[/dim]\n")

    secoes = buscar_manual(queries, model, collection, n_por_query=3)

    for i, secao in enumerate(secoes[:5]):
        cor = "green" if secao["relevancia"] > 0.5 else "yellow" if secao["relevancia"] > 0.3 else "dim"

        texto = secao["texto"]
        if len(texto) > 800:
            texto = texto[:800] + "\n[dim]...(truncado)[/dim]"

        console.print(
            Panel(
                texto,
                title=f"[{cor}]#{i+1} Secao {secao['secao']} - {secao['titulo']} (p.{secao['pagina']}) [{secao['relevancia']:.0%}][/{cor}]",
                subtitle=f"[dim]query: {secao['query_origem']}[/dim]",
                border_style=cor,
                padding=(0, 1),
            )
        )

    # ==================== 3. MODO INTERATIVO ====================
    console.print(
        "\n[bold yellow]3. PERGUNTE SOBRE ESTA CRITICA[/bold yellow]"
    )
    console.print(
        "[dim]Digite uma pergunta para buscar mais no manual, ou 'sair' para encerrar.[/dim]"
        "\n[dim]Ex: 'fisioterapia quantidade maxima', 'quando liberar critica', 'regra de permanencia'[/dim]\n"
    )

    while True:
        try:
            pergunta = Prompt.ask(f"[cyan]Critica {numero}[/cyan]")
        except (KeyboardInterrupt, EOFError):
            break

        if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
            break

        if pergunta.lower() == "/codigo":
            console.print(Syntax(codigo, "typescript", theme="monokai", line_numbers=True))
            continue

        if pergunta.lower() == "/full":
            for secao in secoes:
                console.print(
                    Panel(
                        secao["texto"],
                        title=f"Secao {secao['secao']} - {secao['titulo']} (p.{secao['pagina']}) [{secao['relevancia']:.0%}]",
                        border_style="blue",
                    )
                )
            continue

        resultados = buscar_manual([pergunta], model, collection, n_por_query=5)
        for i, r in enumerate(resultados[:3]):
            cor = "green" if r["relevancia"] > 0.5 else "yellow"
            texto = r["texto"]
            if len(texto) > 800:
                texto = texto[:800] + "\n[dim]...(truncado)[/dim]"
            console.print(
                Panel(
                    texto,
                    title=f"[{cor}]#{i+1} Secao {r['secao']} - {r['titulo']} (p.{r['pagina']}) [{r['relevancia']:.0%}][/{cor}]",
                    border_style=cor,
                    padding=(0, 1),
                )
            )

    console.print("\n[dim]Fim da validacao.[/dim]")


if __name__ == "__main__":
    main()
