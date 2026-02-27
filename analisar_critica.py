"""
Agente de analise critica: confronta o codigo da critica com o Manual SIH/SUS.

Usa RAG para buscar secoes relevantes do manual e a API do Gemini para
raciocinar sobre conformidade, lacunas e riscos.

Uso:
  python analisar_critica.py 129
  python analisar_critica.py 7 --salvar
  python analisar_critica.py --todas --salvar
"""

import io
import json
import os
import re
import sys
from pathlib import Path

import chromadb
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from sentence_transformers import SentenceTransformer

# Re-exports from package (backward compat)
from manual_sih_rag.criticas.analisar import (  # noqa: F401
    PROMPT_SISTEMA,
    analisar_uma_critica,
    montar_prompt,
)
from manual_sih_rag.criticas.validar import (  # noqa: F401
    buscar_manual,
    extrair_logica_hasCritica,
    extrair_termos_busca,
    ler_codigo_critica,
    ler_definicao_critica,
)
from manual_sih_rag.criticas.paths import CRITICAS_TS  # noqa: F401

console = Console()


def carregar_api_key() -> str:
    """Carrega a API key do Gemini."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    key_file = Path.home() / ".config" / "google" / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()

    console.print("[red]API key do Gemini nao encontrada.[/red]")
    console.print("Configure via GEMINI_API_KEY ou ~/.config/google/api_key")
    sys.exit(1)


def main():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    if len(sys.argv) < 2:
        console.print(
            Panel(
                "[bold]Uso:[/bold]\n\n"
                "  python analisar_critica.py <numero>          Analisa uma critica\n"
                "  python analisar_critica.py <numero> --salvar  Analisa e salva resultado\n"
                "  python analisar_critica.py --todas --salvar   Analisa todas as criticas\n",
                title="[bold blue]Agente de Analise Critica SIH/SUS[/bold blue]",
                border_style="blue",
            )
        )
        sys.exit(0)

    salvar = "--salvar" in sys.argv
    todas = "--todas" in sys.argv

    # Carregar dependencias
    console.print("\n[bold blue]Agente de Analise Critica SIH/SUS[/bold blue]\n")
    api_key = carregar_api_key()

    console.print("[dim]Carregando modelo de embeddings...[/dim]")
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    client = chromadb.PersistentClient(path=str(Path(__file__).parent / "db"))
    collection = client.get_collection("manual_sih")
    sys.stderr = old_stderr

    console.print("[green]Sistema carregado.[/green]\n")

    output_dir = Path(__file__).parent / "data" / "analises"

    if todas:
        conteudo = CRITICAS_TS.read_text(encoding="utf-8")
        numeros = sorted(set(int(m) for m in re.findall(r"CRITICA_(\d+):", conteudo)))

        console.print(f"[bold]{len(numeros)} criticas encontradas. Analisando...[/bold]\n")

        resumo = []
        for num in numeros:
            try:
                resultado = analisar_uma_critica(
                    num, model, collection, api_key,
                    salvar=salvar, output_dir=output_dir,
                )
                if resultado:
                    veredicto = "?"
                    for linha in resultado["analise"].split("\n"):
                        if "Veredicto:" in linha or "CONFORME" in linha.upper():
                            veredicto = linha.strip()
                            break
                    resumo.append({"critica": num, "nome": resultado["nome"], "veredicto": veredicto})
            except Exception as e:
                console.print(f"[red]Erro na critica {num}: {e}[/red]")
                resumo.append({"critica": num, "nome": "?", "veredicto": f"ERRO: {e}"})

            console.print("\n" + "=" * 80 + "\n")

        if salvar:
            output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_dir / "resumo_analises.json", "w", encoding="utf-8") as f:
                json.dump(resumo, f, ensure_ascii=False, indent=2)
            console.print(f"\n[green]Resumo salvo em: {output_dir / 'resumo_analises.json'}[/green]")
    else:
        numero = int(sys.argv[1])

        # Header
        definicao = ler_definicao_critica(numero)
        if definicao:
            console.print(
                Panel(
                    f"[bold cyan]{definicao['nome']}[/bold cyan]\n"
                    f"Codigo SIH: [bold]{definicao['codigo']}[/bold]  |  Campos: {', '.join(definicao['campos'])}",
                    title=f"[bold blue]Analise Critica {numero}[/bold blue]",
                    border_style="blue",
                )
            )

        resultado = analisar_uma_critica(
            numero, model, collection, api_key,
            salvar=salvar, output_dir=output_dir,
        )

        if resultado:
            # Modo interativo de follow-up
            console.print(
                "\n[dim]Pergunte algo sobre esta analise, ou 'sair' para encerrar.[/dim]"
            )

            while True:
                try:
                    pergunta = Prompt.ask(f"\n[cyan]Critica {numero}[/cyan]")
                except (KeyboardInterrupt, EOFError):
                    break

                if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
                    break

                if pergunta.startswith("/buscar "):
                    query_extra = pergunta[8:]
                    extras = buscar_manual([query_extra], model, collection, n_por_query=5)
                    for i, r in enumerate(extras[:3]):
                        cor = "green" if r["relevancia"] > 0.5 else "yellow"
                        console.print(
                            Panel(
                                r["texto"][:800],
                                title=f"[{cor}]Secao {r['secao']} - {r['titulo']} (p.{r['pagina']}) [{r['relevancia']:.0%}][/{cor}]",
                                border_style=cor,
                            )
                        )
                    continue

    console.print("\n[dim]Fim da analise.[/dim]")


if __name__ == "__main__":
    main()
