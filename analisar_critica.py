"""
Agente de análise crítica: confronta o código da crítica com o Manual SIH/SUS.

Usa RAG para buscar seções relevantes do manual e a API do Gemini para
raciocinar sobre conformidade, lacunas e riscos.

Uso:
  python analisar_critica.py 129
  python analisar_critica.py 7 --salvar
  python analisar_critica.py 7 --todas    # analisa uma faixa de críticas
"""

import io
import json
import os
import sys
from pathlib import Path

import chromadb
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from sentence_transformers import SentenceTransformer

# Reutilizar funções do validar_critica
from validar_critica import (
    CRITICAS_TS,
    buscar_manual,
    extrair_logica_hasCritica,
    extrair_termos_busca,
    ler_codigo_critica,
    ler_definicao_critica,
)

console = Console()

PROMPT_SISTEMA = """\
Você é um auditor especialista em faturamento hospitalar SIH/SUS.
Sua tarefa é confrontar o CÓDIGO DE UMA CRÍTICA (regra de validação implementada em TypeScript) \
com os TRECHOS DO MANUAL TÉCNICO SIH/SUS que fundamentam essa regra.

Analise com rigor técnico e responda SEMPRE neste formato:

## Resumo da Regra
(O que a crítica valida, em 2-3 frases simples)

## O que o Código Faz
(Descreva a lógica implementada passo a passo, citando variáveis e condições)

## O que o Manual Diz
(Resuma os trechos relevantes do manual, citando seção e página)

## Parecer de Conformidade

**Veredicto: CONFORME | PARCIALMENTE CONFORME | NÃO CONFORME**

### Pontos Conformes
- (liste o que o código implementa corretamente segundo o manual)

### Lacunas no Código
- (regras do manual que o código NÃO implementa ou implementa de forma incompleta)

### Excesso no Código
- (validações que o código faz mas que NÃO têm fundamentação clara no manual)

### Riscos
- (consequências práticas das lacunas: glosas indevidas, rejeições incorretas, etc.)

## Recomendações
- (ações concretas para corrigir lacunas ou excessos, se houver)

Seja preciso. Cite seções e páginas do manual. Não invente regras que não estão nos trechos fornecidos.\
"""


def carregar_api_key() -> str:
    """Carrega a API key do Gemini."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key

    key_file = Path.home() / ".config" / "google" / "api_key"
    if key_file.exists():
        return key_file.read_text().strip()

    console.print("[red]API key do Gemini não encontrada.[/red]")
    console.print("Configure via GEMINI_API_KEY ou ~/.config/google/api_key")
    sys.exit(1)


def chamar_gemini(api_key: str, prompt_usuario: str):
    """Chama a API do Gemini e retorna a resposta com streaming + chat para follow-up."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.0-flash",
        config=genai_types.GenerateContentConfig(
            system_instruction=PROMPT_SISTEMA,
            max_output_tokens=4096,
        ),
    )

    resposta_completa = ""
    console.print()
    for chunk in chat.send_message_stream(prompt_usuario):
        if chunk.text:
            resposta_completa += chunk.text
            console.print(chunk.text, end="", highlight=False)

    console.print()
    return resposta_completa, chat


def montar_prompt(definicao: dict, codigo: str, secoes_manual: list[dict]) -> str:
    """Monta o prompt com código + manual para o Gemini analisar."""
    logica = extrair_logica_hasCritica(codigo)

    secoes_texto = ""
    for i, s in enumerate(secoes_manual[:7]):
        secoes_texto += (
            f"\n--- Trecho {i+1}: Seção {s['secao']} - {s['titulo']} "
            f"(página {s['pagina']}, relevância {s['relevancia']:.0%}) ---\n"
            f"{s['texto']}\n"
        )

    return f"""\
# Crítica {definicao['numero']} — {definicao['nome']}
Código SIH: {definicao['codigo']}
Campos validados: {', '.join(definicao['campos'])}

## CÓDIGO DA CRÍTICA (TypeScript)

```typescript
{logica}
```

## CÓDIGO COMPLETO (com imports e helpers)

```typescript
{codigo}
```

## TRECHOS DO MANUAL SIH/SUS
{secoes_texto}

Analise a conformidade do código com o manual.\
"""


def analisar_uma_critica(
    numero: int,
    model: SentenceTransformer,
    collection,
    api_key: str,
    salvar: bool = False,
) -> dict | None:
    """Executa a análise completa de uma crítica."""
    definicao = ler_definicao_critica(numero)
    if not definicao:
        console.print(f"[red]Crítica {numero} não encontrada em criticas.ts[/red]")
        return None

    codigo = ler_codigo_critica(numero)
    if not codigo:
        console.print(f"[red]Arquivo critica{numero}.ts não encontrado[/red]")
        return None

    # Header
    console.print(
        Panel(
            f"[bold cyan]{definicao['nome']}[/bold cyan]\n"
            f"Código SIH: [bold]{definicao['codigo']}[/bold]  |  Campos: {', '.join(definicao['campos'])}",
            title=f"[bold blue]Análise Crítica {numero}[/bold blue]",
            border_style="blue",
        )
    )

    # Buscar seções do manual
    console.print("[dim]Buscando seções relevantes do manual...[/dim]")
    queries = extrair_termos_busca(codigo, definicao["nome"])
    secoes = buscar_manual(queries, model, collection, n_por_query=3)

    console.print(
        f"[dim]{len(secoes)} trechos encontrados — enviando para análise...[/dim]"
    )

    # Montar prompt e chamar Gemini
    prompt = montar_prompt(definicao, codigo, secoes)
    resposta, chat = chamar_gemini(api_key, prompt)

    resultado = {
        "critica": numero,
        "codigo_sih": definicao["codigo"],
        "nome": definicao["nome"],
        "campos": definicao["campos"],
        "secoes_consultadas": [
            {"secao": s["secao"], "titulo": s["titulo"], "pagina": s["pagina"], "relevancia": s["relevancia"]}
            for s in secoes[:7]
        ],
        "analise": resposta,
    }

    if salvar:
        output_dir = Path(__file__).parent / "data" / "analises"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"analise_critica_{numero}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        md_path = output_dir / f"analise_critica_{numero}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Análise Crítica {numero} — {definicao['nome']}\n\n")
            f.write(f"Código SIH: {definicao['codigo']}  \n")
            f.write(f"Campos: {', '.join(definicao['campos'])}  \n\n")
            f.write(resposta)

        console.print(f"\n[green]Salvo em: {output_path}[/green]")
        console.print(f"[green]Salvo em: {md_path}[/green]")

    # Modo interativo de follow-up
    console.print(
        "\n[dim]Pergunte algo sobre esta análise, ou 'sair' para encerrar.[/dim]"
    )

    while True:
        try:
            pergunta = Prompt.ask(f"\n[cyan]Crítica {numero}[/cyan]")
        except (KeyboardInterrupt, EOFError):
            break

        if pergunta.lower() in ("sair", "exit", "quit", "q", ""):
            break

        # Se pedir para buscar mais no manual
        if pergunta.startswith("/buscar "):
            query_extra = pergunta[8:]
            extras = buscar_manual([query_extra], model, collection, n_por_query=5)
            for i, r in enumerate(extras[:3]):
                cor = "green" if r["relevancia"] > 0.5 else "yellow"
                console.print(
                    Panel(
                        r["texto"][:800],
                        title=f"[{cor}]Seção {r['secao']} - {r['titulo']} (p.{r['pagina']}) [{r['relevancia']:.0%}][/{cor}]",
                        border_style=cor,
                    )
                )
            continue

        # Perguntar ao Gemini com contexto da análise (chat mantém histórico)
        resposta_followup = ""
        console.print()
        for chunk in chat.send_message_stream(pergunta):
            if chunk.text:
                resposta_followup += chunk.text
                console.print(chunk.text, end="", highlight=False)
        console.print()

    return resultado


def main():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    if len(sys.argv) < 2:
        console.print(
            Panel(
                "[bold]Uso:[/bold]\n\n"
                "  python analisar_critica.py <numero>          Analisa uma crítica\n"
                "  python analisar_critica.py <numero> --salvar  Analisa e salva resultado\n"
                "  python analisar_critica.py --todas --salvar   Analisa todas as críticas\n",
                title="[bold blue]Agente de Análise Crítica SIH/SUS[/bold blue]",
                border_style="blue",
            )
        )
        sys.exit(0)

    salvar = "--salvar" in sys.argv
    todas = "--todas" in sys.argv

    # Carregar dependências
    console.print("\n[bold blue]Agente de Análise Crítica SIH/SUS[/bold blue]\n")
    api_key = carregar_api_key()

    console.print("[dim]Carregando modelo de embeddings...[/dim]")
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    client = chromadb.PersistentClient(path=str(Path(__file__).parent / "db"))
    collection = client.get_collection("manual_sih")
    sys.stderr = old_stderr

    console.print("[green]Sistema carregado.[/green]\n")

    if todas:
        # Analisar todas as críticas encontradas
        import re
        conteudo = CRITICAS_TS.read_text(encoding="utf-8")
        numeros = sorted(set(int(m) for m in re.findall(r"CRITICA_(\d+):", conteudo)))

        console.print(f"[bold]{len(numeros)} críticas encontradas. Analisando...[/bold]\n")

        resumo = []
        for num in numeros:
            try:
                resultado = analisar_uma_critica(num, model, collection, api_key, salvar=salvar)
                if resultado:
                    # Extrair veredicto do texto
                    veredicto = "?"
                    for linha in resultado["analise"].split("\n"):
                        if "Veredicto:" in linha or "CONFORME" in linha.upper():
                            veredicto = linha.strip()
                            break
                    resumo.append({"critica": num, "nome": resultado["nome"], "veredicto": veredicto})
            except Exception as e:
                console.print(f"[red]Erro na crítica {num}: {e}[/red]")
                resumo.append({"critica": num, "nome": "?", "veredicto": f"ERRO: {e}"})

            console.print("\n" + "=" * 80 + "\n")

        # Resumo final
        if salvar:
            output_dir = Path(__file__).parent / "data" / "analises"
            output_dir.mkdir(parents=True, exist_ok=True)
            with open(output_dir / "resumo_analises.json", "w", encoding="utf-8") as f:
                json.dump(resumo, f, ensure_ascii=False, indent=2)
            console.print(f"\n[green]Resumo salvo em: {output_dir / 'resumo_analises.json'}[/green]")
    else:
        numero = int(sys.argv[1])
        analisar_uma_critica(numero, model, collection, api_key, salvar=salvar)

    console.print("\n[dim]Fim da análise.[/dim]")


if __name__ == "__main__":
    main()
