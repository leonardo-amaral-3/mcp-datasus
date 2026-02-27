"""
Valida uma crítica mostrando:
  1. RESUMO em português do que o código faz (lido do .ts real)
  2. SEÇÕES do manual que fundamentam essa regra (buscando pelo que o código FAZ, não pelo nome)
  3. Modo interativo para perguntar sobre a crítica

Uso:
  python validar_critica.py 129
  python validar_critica.py 7
"""

import json
import os
import re
import sys
import textwrap
from pathlib import Path

import chromadb
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table
from sentence_transformers import SentenceTransformer

console = Console()

CRITICAS_DIR = Path(__file__).parent.parent.parent / "processos-criticas" / "src" / "criticas"
CRITICAS_TS = Path(__file__).parent.parent.parent / "processos-criticas" / "src" / "constants" / "criticas.ts"
PROJETO_DIR = Path(__file__).parent.parent.parent / "processos-criticas"


def ler_definicao_critica(numero: int) -> dict | None:
    conteudo = CRITICAS_TS.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"CRITICA_{numero}:\s*\{{\s*"
        r"codigo:\s*'(\d+)'\s*,\s*"
        r"nome:\s*'([^']+)'\s*,\s*"
        r"campos:\s*\[([^\]]*)\]",
        re.MULTILINE,
    )
    match = pattern.search(conteudo)
    if not match:
        return None
    campos_raw = match.group(3)
    campos = [c.strip().strip("'\"") for c in campos_raw.split(",") if c.strip()]
    return {"numero": numero, "codigo": match.group(1), "nome": match.group(2), "campos": campos}


def ler_codigo_critica(numero: int) -> str | None:
    arquivo = CRITICAS_DIR / f"critica{numero}" / f"critica{numero}.ts"
    if not arquivo.exists():
        return None
    return arquivo.read_text(encoding="utf-8")


def extrair_logica_hasCritica(codigo: str) -> str:
    """Extrai só a função hasCritica, removendo linhas de debug."""
    linhas = codigo.split("\n")
    inicio = None
    # Encontrar início da hasCritica
    for i, linha in enumerate(linhas):
        if "hasCritica" in linha and ("const" in linha or "async" in linha):
            inicio = i
            break

    if inicio is None:
        # Fallback: mostrar o código sem imports e sem o wrapper final
        resultado = []
        for linha in linhas:
            stripped = linha.strip()
            if stripped.startswith("import ") or stripped.startswith("} from"):
                continue
            if stripped.startswith("if (isDebug)") or stripped.startswith("console.log"):
                continue
            if "DEBUG" in stripped and "const DEBUG" not in stripped:
                continue
            resultado.append(linha)
        return "\n".join(resultado).strip()

    # Rastrear nível de chaves a partir do início
    nivel = 0
    resultado = []
    encontrou_primeira_chave = False

    for i in range(inicio, len(linhas)):
        linha = linhas[i]
        stripped = linha.strip()

        # Pular linhas de debug
        if stripped.startswith("if (isDebug)") or stripped.startswith("console.log"):
            continue
        if "DEBUG" in stripped and "const DEBUG" not in stripped:
            continue

        resultado.append(linha)

        for ch in linha:
            if ch == "{":
                nivel += 1
                encontrou_primeira_chave = True
            elif ch == "}":
                nivel -= 1

        if encontrou_primeira_chave and nivel <= 0:
            break

    return "\n".join(resultado)


def extrair_termos_busca(codigo: str, nome: str) -> list[str]:
    """Analisa o código REAL para gerar queries de busca no manual."""
    termos = []

    # Detectar imports e constantes usadas
    if "PROCEDIMENTOS_FISIOTERAPIA" in codigo:
        termos.append("fisioterapia atendimento fisioterapêutico quantidade máxima por dia internação")
    if "calcularDiasInternacao" in codigo:
        termos.append("dias de internação permanência cálculo por competência")
    if "rlProcedimentoCid" in codigo:
        termos.append("compatibilidade CID diagnóstico procedimento SIGTAP CID-10")
    if "rlProcedimentoSexo" in codigo or "sexoPaciente" in codigo.lower():
        termos.append("sexo paciente incompatível procedimento diagnóstico")
    if "idadeMinima" in codigo or "idadeMaxima" in codigo or "calcularIdade" in codigo:
        termos.append("idade paciente mínima máxima procedimento faixa etária")
    if "permanencia" in codigo.lower() or "mediaPermanencia" in codigo.lower():
        termos.append("média permanência dias SIGTAP liberação crítica")
    if "duplici" in codigo.lower():
        termos.append("duplicidade AIH mesmo paciente reinternação 03 dias bloqueio")
    if "opm" in codigo.lower() or "OPM" in codigo:
        termos.append("OPM órteses próteses materiais especiais compatibilidade quantidade")
    if "cbo" in codigo.lower():
        termos.append("CBO classificação brasileira ocupações médico profissional CNES")
    if "cnes" in codigo.lower():
        termos.append("CNES cadastro nacional estabelecimentos habilitação")
    if "anestesia" in codigo.lower():
        termos.append("anestesia regional geral sedação cirurgião obstétrica")
    if "hemoterapia" in codigo.lower() or "transfus" in codigo.lower():
        termos.append("hemoterapia transfusão sangue agência transfusional")
    if "leito" in codigo.lower():
        termos.append("especialidade leito UTI UCI CNES cadastro")
    if "acompanhante" in codigo.lower() or "diaria" in codigo.lower():
        termos.append("diária acompanhante idoso gestante UTI")
    if "transplante" in codigo.lower():
        termos.append("transplante órgãos doação retirada intercorrência")
    if "politraumatizado" in codigo.lower() or "cirurgiaMultipla" in codigo.lower():
        termos.append("politraumatizado cirurgia múltipla tratamento")
    if "motivoSaida" in codigo or "motivoApresentacao" in codigo.lower():
        termos.append("motivo apresentação alta permanência transferência óbito")
    if "quantidadeRealizada" in codigo or "quantidadeMaxima" in codigo.lower():
        termos.append("quantidade máxima procedimentos AIH limite SIGTAP")
    if "competencia" in codigo.lower():
        termos.append("competência execução processamento apresentação AIH")

    # Sempre incluir o nome da crítica como query
    termos.append(nome)

    return termos


def buscar_manual(queries: list[str], model, collection, n_por_query: int = 3) -> list[dict]:
    """Busca no manual usando múltiplas queries, deduplicando e ranqueando."""
    # Usar busca híbrida se disponível
    try:
        from busca_hibrida import buscar_manual_hibrida, _bm25
        if _bm25 is not None:
            return buscar_manual_hibrida(queries, model, collection, n_por_query)
    except (ImportError, Exception):
        pass

    # Fallback: busca vetorial original
    todos = {}

    for query in queries:
        embedding = model.encode([query], normalize_embeddings=True)
        resultado = collection.query(
            query_embeddings=[embedding[0].tolist()],
            n_results=n_por_query,
            include=["documents", "metadatas", "distances"],
        )
        for i in range(len(resultado["ids"][0])):
            rid = resultado["ids"][0][i]
            score = 1 - resultado["distances"][0][i]
            if rid not in todos or score > todos[rid]["relevancia"]:
                texto = resultado["documents"][0][i]
                if texto.startswith("[Manual"):
                    idx = texto.find("]\n\n")
                    if idx > 0:
                        texto = texto[idx + 3 :]
                todos[rid] = {
                    "id": rid,
                    "secao": resultado["metadatas"][0][i]["secao"],
                    "titulo": resultado["metadatas"][0][i]["titulo"].split("\n")[0].strip(),
                    "pagina": resultado["metadatas"][0][i]["pagina"],
                    "texto": texto,
                    "relevancia": round(score, 3),
                    "query_origem": query[:60],
                }

    return sorted(todos.values(), key=lambda x: -x["relevancia"])


def listar_arquivos_critica(numero: int) -> list[str]:
    """Lista todos os arquivos relacionados à crítica."""
    pasta = CRITICAS_DIR / f"critica{numero}"
    arquivos = []
    if pasta.exists():
        for f in sorted(pasta.rglob("*.ts")):
            arquivos.append(str(f.relative_to(PROJETO_DIR)))
    # Testes
    tests_dir = PROJETO_DIR / "__tests__"
    if tests_dir.exists():
        for f in sorted(tests_dir.rglob(f"*critica{numero}*")):
            arquivos.append(str(f.relative_to(PROJETO_DIR)))
    return arquivos


def main():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    if len(sys.argv) < 2:
        console.print("[bold]Uso:[/bold] python validar_critica.py <numero_critica>")
        console.print("  Ex: python validar_critica.py 129")
        sys.exit(0)

    numero = int(sys.argv[1])

    # Carregar
    console.print("[dim]Carregando...[/dim]")
    import io
    old = sys.stderr
    sys.stderr = io.StringIO()
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    client = chromadb.PersistentClient(path=str(Path(__file__).parent / "db"))
    collection = client.get_collection("manual_sih")
    sys.stderr = old

    # Ler crítica
    definicao = ler_definicao_critica(numero)
    if not definicao:
        console.print(f"[red]Crítica {numero} não encontrada em criticas.ts[/red]")
        sys.exit(1)

    codigo = ler_codigo_critica(numero)
    if not codigo:
        console.print(f"[red]Arquivo critica{numero}.ts não encontrado[/red]")
        sys.exit(1)

    # ==================== HEADER ====================
    console.print()
    console.print(
        Panel(
            f"[bold cyan]{definicao['nome']}[/bold cyan]\n"
            f"Código SIH: [bold]{definicao['codigo']}[/bold]  |  Campos: {', '.join(definicao['campos'])}",
            title=f"[bold blue]Crítica {numero}[/bold blue]",
            border_style="blue",
        )
    )

    # ==================== 1. CÓDIGO ====================
    console.print("\n[bold yellow]1. O QUE O CÓDIGO FAZ[/bold yellow]")
    console.print(f"[dim]Arquivo: processos-criticas/src/criticas/critica{numero}/critica{numero}.ts[/dim]\n")

    logica = extrair_logica_hasCritica(codigo)
    console.print(
        Syntax(logica, "typescript", theme="monokai", line_numbers=False, word_wrap=True)
    )

    # Arquivos relacionados
    arquivos = listar_arquivos_critica(numero)
    if len(arquivos) > 1:
        console.print(f"\n[dim]Arquivos relacionados: {', '.join(arquivos)}[/dim]")

    # ==================== 2. MANUAL ====================
    console.print("\n[bold yellow]2. O QUE O MANUAL DIZ[/bold yellow]")

    # Gerar queries inteligentes baseadas no código REAL
    queries = extrair_termos_busca(codigo, definicao["nome"])
    console.print(f"[dim]Buscando por: {' | '.join(q[:50] for q in queries[:4])}[/dim]\n")

    secoes = buscar_manual(queries, model, collection, n_por_query=3)

    # Mostrar top 5
    for i, secao in enumerate(secoes[:5]):
        cor = "green" if secao["relevancia"] > 0.5 else "yellow" if secao["relevancia"] > 0.3 else "dim"

        texto = secao["texto"]
        if len(texto) > 800:
            texto = texto[:800] + "\n[dim]...(truncado)[/dim]"

        console.print(
            Panel(
                texto,
                title=f"[{cor}]#{i+1} Seção {secao['secao']} - {secao['titulo']} (p.{secao['pagina']}) [{secao['relevancia']:.0%}][/{cor}]",
                subtitle=f"[dim]query: {secao['query_origem']}[/dim]",
                border_style=cor,
                padding=(0, 1),
            )
        )

    # ==================== 3. MODO INTERATIVO ====================
    console.print(
        "\n[bold yellow]3. PERGUNTE SOBRE ESTA CRÍTICA[/bold yellow]"
    )
    console.print(
        "[dim]Digite uma pergunta para buscar mais no manual, ou 'sair' para encerrar.[/dim]"
        "\n[dim]Ex: 'fisioterapia quantidade máxima', 'quando liberar crítica', 'regra de permanência'[/dim]\n"
    )

    while True:
        try:
            pergunta = Prompt.ask(f"[cyan]Crítica {numero}[/cyan]")
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
                        title=f"Seção {secao['secao']} - {secao['titulo']} (p.{secao['pagina']}) [{secao['relevancia']:.0%}]",
                        border_style="blue",
                    )
                )
            continue

        # Buscar no manual
        resultados = buscar_manual([pergunta], model, collection, n_por_query=5)
        for i, r in enumerate(resultados[:3]):
            cor = "green" if r["relevancia"] > 0.5 else "yellow"
            texto = r["texto"]
            if len(texto) > 800:
                texto = texto[:800] + "\n[dim]...(truncado)[/dim]"
            console.print(
                Panel(
                    texto,
                    title=f"[{cor}]#{i+1} Seção {r['secao']} - {r['titulo']} (p.{r['pagina']}) [{r['relevancia']:.0%}][/{cor}]",
                    border_style=cor,
                    padding=(0, 1),
                )
            )

    console.print("\n[dim]Fim da validação.[/dim]")


if __name__ == "__main__":
    main()
