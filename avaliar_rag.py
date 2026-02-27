"""
Avaliacao do pipeline RAG do manual SIH/SUS.

Compara pipeline original (vector-only) com pipeline hibrido (BM25+Vector+Reranker)
usando metricas de retrieval: Recall@K e MRR.

O baseline vector-only faz busca direta no ChromaDB (cosine similarity),
sem passar pelo pipeline hibrido, garantindo comparacao justa.
"""

import io
import os
import sys

import chromadb
from rich.console import Console
from rich.table import Table
from sentence_transformers import SentenceTransformer


# ---------------------------------------------------------------------------
# Eval set calibrado contra o conteudo real indexado (Manual SIH 2012/2017 + portarias)
# ---------------------------------------------------------------------------
EVAL_SET = [
    {
        "query": "compatibilidade procedimento principal com diagnóstico CID",
        "secoes_esperadas": ["62.1", "63.7"],
        "descricao": "CID x procedimento",
    },
    {
        "query": "sexo do paciente incompatível com procedimento",
        "secoes_esperadas": ["26", "52"],
        "descricao": "Sexo x procedimento",
    },
    {
        "query": "idade mínima e máxima para procedimento faixa etária",
        "secoes_esperadas": ["57.2", "63.2"],
        "descricao": "Faixa etária",
    },
    {
        "query": "dias de permanência média SIGTAP",
        "secoes_esperadas": ["57.1", "63.1"],
        "descricao": "Média de permanência",
    },
    {
        "query": "OPM órteses próteses compatibilidade com procedimento cirúrgico",
        "secoes_esperadas": ["12.1", "11.30", "16.1"],
        "descricao": "Regras de OPM",
    },
    {
        "query": "duplicidade de AIH mesmo paciente reinternação",
        "secoes_esperadas": ["63.8", "58.1", "58.2"],
        "descricao": "Duplicidade",
    },
    {
        "query": "politraumatizado múltiplas cirurgias",
        "secoes_esperadas": ["9.1", "9.2", "11.3"],
        "descricao": "Politraumatizado",
    },
    {
        "query": "fisioterapia quantidade máxima atendimentos por dia",
        "secoes_esperadas": ["11.23"],
        "descricao": "Fisioterapia",
    },
    {
        "query": "diária de acompanhante UTI idoso",
        "secoes_esperadas": ["13.2", "10.1"],
        "descricao": "Diária acompanhante",
    },
    {
        "query": "mudança de procedimento durante internação",
        "secoes_esperadas": ["8.2", "8.3", "8.4"],
        "descricao": "Mudança procedimento",
    },
    {
        "query": "laudo médico AIH autorização internação",
        "secoes_esperadas": ["4.3", "4.1"],
        "descricao": "Laudo AIH",
    },
    {
        "query": "caráter de atendimento eletivo urgência",
        "secoes_esperadas": ["6.2"],
        "descricao": "Caráter atendimento",
    },
    {
        "query": "050046",
        "secoes_esperadas": ["26"],
        "descricao": "Busca por código SIH (keyword)",
    },
    {
        "query": "numeração de AIH emissão faixa numérica",
        "secoes_esperadas": ["4.5", "3.3", "4.4.3"],
        "descricao": "Numeração AIH",
    },
    {
        "query": "hemoterapia transfusão sangue regras",
        "secoes_esperadas": ["21.3", "16.5", "16.2", "11.22"],
        "descricao": "Hemoterapia",
    },
]


def _extrair_secao(resultado: dict) -> str:
    """Extract secao from a result dict, handling both schemas."""
    secao = resultado.get("secao")
    if secao is None:
        secao = resultado.get("metadata", {}).get("secao", "")
    return str(secao)


def recall_at_k(resultados: list[dict], secoes_esperadas: list[str], k: int) -> float:
    """Recall@K: fraction of expected sections found in the top-K results."""
    if not secoes_esperadas:
        return 1.0
    top_k_secoes = {_extrair_secao(r) for r in resultados[:k]}
    esperadas = set(secoes_esperadas)
    encontradas = top_k_secoes & esperadas
    return len(encontradas) / len(esperadas)


def mrr(resultados: list[dict], secoes_esperadas: list[str]) -> float:
    """Mean Reciprocal Rank: 1/rank of the first relevant result."""
    esperadas = set(secoes_esperadas)
    for i, r in enumerate(resultados, start=1):
        if _extrair_secao(r) in esperadas:
            return 1.0 / i
    return 0.0


# ---------------------------------------------------------------------------
# Baseline: busca vetorial pura (direto no ChromaDB, sem delegacao hibrida)
# ---------------------------------------------------------------------------
def buscar_vetorial_puro(
    pergunta: str,
    model: SentenceTransformer,
    collection,
    n_resultados: int = 5,
) -> list[dict]:
    """Busca PURAMENTE vetorial — query ChromaDB cosine direto, sem BM25/reranker."""
    embedding = model.encode([pergunta], normalize_embeddings=True)
    resultado = collection.query(
        query_embeddings=[embedding[0].tolist()],
        n_results=n_resultados,
        include=["documents", "metadatas", "distances"],
    )

    items: list[dict] = []
    for i in range(len(resultado["ids"][0])):
        texto = resultado["documents"][0][i]
        meta = resultado["metadatas"][0][i]
        score = 1.0 - resultado["distances"][0][i]

        # Strip "[Manual..." prefix (same as original buscar())
        if texto.startswith("[Manual"):
            idx = texto.find("]\n\n")
            if idx > 0:
                texto = texto[idx + 3:]

        titulo = str(meta.get("titulo", "")).split("\n")[0].strip()
        pagina = meta.get("pagina", 0)
        try:
            pagina = int(pagina)
        except (ValueError, TypeError):
            pagina = 0

        items.append(
            {
                "id": resultado["ids"][0][i],
                "texto": texto,
                "metadata": {
                    "secao": str(meta.get("secao", "")),
                    "titulo": titulo,
                    "pagina": pagina,
                },
                "score": float(score),
            }
        )

    return items


def avaliar_pipeline(
    buscar_fn,
    model,
    collection,
    eval_set: list[dict] | None = None,
    k_values: list[int] | None = None,
    label: str = "",
) -> dict[str, float]:
    """Run the evaluation set through a search function and compute aggregate metrics."""
    if eval_set is None:
        eval_set = EVAL_SET
    if k_values is None:
        k_values = [5, 10]

    max_k = max(k_values)
    somas: dict[str, float] = {}
    contagem = len(eval_set)

    for entry in eval_set:
        resultados = buscar_fn(entry["query"], model, collection, n_resultados=max_k)
        for k in k_values:
            chave = f"Recall@{k}"
            somas[chave] = somas.get(chave, 0.0) + recall_at_k(
                resultados, entry["secoes_esperadas"], k
            )
        somas["MRR"] = somas.get("MRR", 0.0) + mrr(
            resultados, entry["secoes_esperadas"]
        )

    medias = {metrica: valor / contagem for metrica, valor in somas.items()}
    return medias


def _exibir_detalhes(buscar_old, buscar_new, model, collection):
    """Show per-query comparison for debugging."""
    console = Console()
    console.print("\n[bold]Detalhes por query:[/bold]\n")

    table = Table(show_lines=True)
    table.add_column("Query", width=35)
    table.add_column("Esperado", width=16)
    table.add_column("Vec-only top3", width=16)
    table.add_column("Híbrido top3", width=16)
    table.add_column("Hit?", width=8)

    for entry in EVAL_SET:
        q = entry["query"]
        esperadas = set(entry["secoes_esperadas"])

        old_results = buscar_old(q, model, collection, n_resultados=10)
        new_results = buscar_new(q, model, collection, n_resultados=10)

        old_secoes = [_extrair_secao(r) for r in old_results[:3]]
        new_secoes = [_extrair_secao(r) for r in new_results[:3]]

        old_hit = any(_extrair_secao(r) in esperadas for r in old_results[:5])
        new_hit = any(_extrair_secao(r) in esperadas for r in new_results[:5])

        hit_str = ""
        if new_hit and not old_hit:
            hit_str = "[green]+NEW[/green]"
        elif old_hit and not new_hit:
            hit_str = "[red]-LOST[/red]"
        elif old_hit and new_hit:
            hit_str = "[dim]both[/dim]"
        else:
            hit_str = "[dim]none[/dim]"

        table.add_row(
            q[:33],
            ", ".join(sorted(esperadas)),
            ", ".join(old_secoes),
            ", ".join(new_secoes),
            hit_str,
        )

    console.print(table)


def main():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    console = Console()
    console.print("\n[bold blue]Avaliação do Pipeline RAG[/bold blue]\n")

    # Load model and collection directly (NOT through carregar_sistema which triggers hybrid)
    console.print("[dim]Carregando modelo e banco vetorial...[/dim]")
    old_err = sys.stderr
    sys.stderr = io.StringIO()
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    from pathlib import Path

    db_dir = Path(__file__).parent / "db"
    client = chromadb.PersistentClient(path=str(db_dir))
    collection = client.get_collection("manual_sih")
    sys.stderr = old_err
    console.print(f"[green]Carregado: {collection.count()} chunks.[/green]")

    # Evaluate vector-only baseline (pure cosine, no hybrid)
    console.print("\n[dim]Avaliando pipeline VECTOR-ONLY (cosine puro)...[/dim]")
    metricas_old = avaliar_pipeline(
        buscar_vetorial_puro, model, collection, label="Vector-only"
    )

    # Try hybrid
    metricas_new = None
    buscar_hibrida_fn = None
    try:
        from busca_hibrida import buscar_hibrida, carregar_sistema_hibrido

        console.print("[dim]Carregando sistema híbrido...[/dim]")
        carregar_sistema_hibrido(carregar_reranker=True)
        from busca_hibrida import _bm25 as bm25_check

        if bm25_check is not None:
            buscar_hibrida_fn = buscar_hibrida
            console.print(
                "[dim]Avaliando pipeline HÍBRIDO (BM25+Vector+Reranker)...[/dim]"
            )
            metricas_new = avaliar_pipeline(
                buscar_hibrida, model, collection, label="Híbrido"
            )
    except ImportError:
        console.print("[yellow]Pipeline híbrido não disponível.[/yellow]")

    # Display comparison table
    table = Table(title="Comparação de Pipelines RAG")
    table.add_column("Métrica", style="cyan")
    table.add_column("Vector-only", justify="right")
    if metricas_new:
        table.add_column("Híbrido", justify="right")
        table.add_column("Delta", justify="right")

    for metric in sorted(metricas_old.keys()):
        old_val = metricas_old[metric]
        row = [metric, f"{old_val:.1%}"]
        if metricas_new:
            new_val = metricas_new[metric]
            delta = new_val - old_val
            color = "green" if delta > 0 else "red" if delta < 0 else "white"
            row.extend([f"{new_val:.1%}", f"[{color}]{delta:+.1%}[/{color}]"])
        table.add_row(*row)

    console.print(table)

    # Per-query detail
    if metricas_new and buscar_hibrida_fn is not None:
        _exibir_detalhes(buscar_vetorial_puro, buscar_hibrida_fn, model, collection)


if __name__ == "__main__":
    main()
