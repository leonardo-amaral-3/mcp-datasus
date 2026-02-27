"""Stateful hybrid search pipeline — manages global state and high-level API.

Provides drop-in replacements for:
  - consulta_manual.buscar()         -> buscar_hibrida()
  - validar_critica.buscar_manual()  -> buscar_manual_hibrida()
"""

from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from .hints import CRITICA_HINTS
from .paths import DATA_DIR, DB_DIR
from .search_primitives import (
    buscar_bm25,
    buscar_vetorial,
    decompor_query,
    extrair_filtros_metadata,
    reciprocal_rank_fusion,
    rerancar,
    resolver_parent_chunks,
)

# ---------------------------------------------------------------------------
# Module globals (set by carregar_sistema_hibrido)
# ---------------------------------------------------------------------------
_model: SentenceTransformer | None = None
_collection: Any = None
_bm25: BM25Okapi | None = None
_reranker: CrossEncoder | None = None
_bm25_ids: list[str] = []
_bm25_metadatas: list[dict] = []
_parent_map: dict[str, str] = {}
_chunks_by_id: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# pipeline_busca
# ---------------------------------------------------------------------------
def pipeline_busca(
    pergunta: str,
    n_resultados: int = 5,
    usar_reranker: bool = True,
    usar_decomposicao: bool = True,
    usar_parent: bool = True,
    where: dict | None = None,
) -> list[tuple[str, float, dict]]:
    """Full pipeline: decomposition + BM25 + vector + RRF + reranker + parent."""
    if where is None:
        where = extrair_filtros_metadata(pergunta)

    if usar_decomposicao:
        sub_queries = decompor_query(pergunta, CRITICA_HINTS)
    else:
        sub_queries = [pergunta]

    all_bm25: list[tuple[str, float]] = []
    all_vec: list[tuple[str, float]] = []

    for sq in sub_queries:
        all_bm25.extend(
            buscar_bm25(sq, _bm25, _bm25_ids, _bm25_metadatas, n_resultados=20, where=where)
        )
        all_vec.extend(
            buscar_vetorial(sq, _model, _collection, n_resultados=20, where=where)
        )

    fused = reciprocal_rank_fusion(all_bm25, all_vec, k=60)

    palavras = pergunta.strip().split()
    query_curta = len(palavras) <= 2 or pergunta.strip().isdigit()
    if usar_reranker and not query_curta:
        top_rerank = max(20, n_resultados * 3)
        reranked = rerancar(
            pergunta, fused[:top_rerank], _chunks_by_id, _reranker, top_n=n_resultados * 2
        )
    else:
        reranked = fused[: n_resultados * 2]

    if usar_parent and _parent_map:
        reranked = resolver_parent_chunks(reranked, _parent_map)

    final: list[tuple[str, float, dict]] = []
    for chunk_id, score in reranked:
        chunk = _chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        meta = {k: v for k, v in chunk.items() if k not in ("texto", "contexto")}
        final.append((chunk_id, score, meta))

    return final[:n_resultados]


# ---------------------------------------------------------------------------
# buscar_hibrida  (drop-in for consulta_manual.buscar)
# ---------------------------------------------------------------------------
def buscar_hibrida(
    pergunta: str,
    model: SentenceTransformer,
    collection: Any,
    n_resultados: int = 5,
) -> list[dict]:
    """Drop-in replacement for consulta_manual.buscar().

    Returns: [{"id", "texto", "metadata": {"secao", "titulo", "pagina"}, "score"}]
    """
    resultados = pipeline_busca(pergunta, n_resultados=n_resultados)

    items: list[dict] = []
    for chunk_id, score, meta in resultados:
        texto = _resolver_texto_chunk(chunk_id) or ""

        if texto.startswith("[Manual"):
            idx = texto.find("]\n\n")
            if idx > 0:
                texto = texto[idx + 3:]

        titulo = str(meta.get("titulo", ""))
        titulo = titulo.split("\n")[0].strip()

        pagina = meta.get("pagina", 0)
        if not isinstance(pagina, int):
            try:
                pagina = int(pagina)
            except (ValueError, TypeError):
                pagina = 0

        items.append({
            "id": str(chunk_id),
            "texto": texto,
            "metadata": {
                "secao": str(meta.get("secao", "")),
                "titulo": titulo,
                "pagina": pagina,
            },
            "score": float(score),
        })

    return items


# ---------------------------------------------------------------------------
# buscar_manual_hibrida  (drop-in for validar_critica.buscar_manual)
# ---------------------------------------------------------------------------
def buscar_manual_hibrida(
    queries: list[str],
    model: SentenceTransformer,
    collection: Any,
    n_por_query: int = 3,
) -> list[dict]:
    """Drop-in replacement for validar_critica.buscar_manual().

    Returns: [{"id", "secao", "titulo", "pagina", "texto", "relevancia", "query_origem"}]
    """
    todos: dict[str, dict] = {}

    for query in queries:
        resultados = pipeline_busca(
            query, n_resultados=n_por_query, usar_decomposicao=False,
        )
        for chunk_id, score, meta in resultados:
            if chunk_id not in todos or score > todos[chunk_id]["relevancia"]:
                texto = _resolver_texto_chunk(chunk_id) or ""

                if texto.startswith("[Manual"):
                    idx = texto.find("]\n\n")
                    if idx > 0:
                        texto = texto[idx + 3:]

                titulo = str(meta.get("titulo", ""))
                titulo = titulo.split("\n")[0].strip()

                pagina = meta.get("pagina", 0)
                if not isinstance(pagina, int):
                    try:
                        pagina = int(pagina)
                    except (ValueError, TypeError):
                        pagina = 0

                todos[chunk_id] = {
                    "id": str(chunk_id),
                    "secao": str(meta.get("secao", "")),
                    "titulo": titulo,
                    "pagina": pagina,
                    "texto": texto,
                    "relevancia": round(float(score), 3),
                    "query_origem": query[:60],
                }

    return sorted(todos.values(), key=lambda x: -x["relevancia"])


# ---------------------------------------------------------------------------
# carregar_sistema_hibrido
# ---------------------------------------------------------------------------
def carregar_sistema_hibrido(
    db_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    carregar_reranker: bool = True,
) -> tuple[SentenceTransformer, Any]:
    """Load all components of the hybrid system. Returns (model, collection)."""
    global _model, _collection, _bm25, _reranker
    global _bm25_ids, _bm25_metadatas, _parent_map, _chunks_by_id

    from rich.console import Console
    console = Console()

    if db_dir is None:
        db_dir = DB_DIR
    else:
        db_dir = Path(db_dir)
    if data_dir is None:
        data_dir = DATA_DIR
    else:
        data_dir = Path(data_dir)

    # 1. SentenceTransformer
    console.print("[dim]Carregando modelo de embeddings...[/dim]")
    _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    console.print("[green]  Modelo de embeddings carregado.[/green]")

    # 2. ChromaDB collection
    import chromadb

    console.print("[dim]Conectando ao banco vetorial...[/dim]")
    chroma_host = os.getenv("CHROMA_HOST")
    if chroma_host:
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    else:
        client = chromadb.PersistentClient(path=str(db_dir))
    _collection = client.get_collection("manual_sih")
    console.print(
        f"[green]  Banco vetorial conectado: {_collection.count()} chunks.[/green]"
    )

    # 3. BM25 index
    bm25_path = data_dir / "bm25_index.pkl"
    if bm25_path.exists():
        console.print("[dim]Carregando indice BM25...[/dim]")
        with open(bm25_path, "rb") as f:
            bm25_data = pickle.load(f)
        _bm25 = bm25_data.get("bm25")
        _bm25_ids = bm25_data.get("ids", [])
        _bm25_metadatas = bm25_data.get("metadatas", [])
        console.print(f"[green]  BM25 carregado: {len(_bm25_ids)} documentos.[/green]")
    else:
        console.print(
            "[yellow]  BM25 index nao encontrado (bm25_index.pkl). Busca BM25 desabilitada.[/yellow]"
        )
        _bm25 = None
        _bm25_ids = []
        _bm25_metadatas = []

    # 4. CrossEncoder reranker
    if carregar_reranker:
        console.print("[dim]Carregando reranker (CrossEncoder)...[/dim]")
        try:
            _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            console.print("[green]  Reranker carregado.[/green]")
        except Exception as e:
            console.print(f"[yellow]  Reranker nao carregado: {e}[/yellow]")
            _reranker = None
    else:
        _reranker = None

    # 5. Parent-child map
    parent_path = data_dir / "parent_child_map.json"
    if parent_path.exists():
        console.print("[dim]Carregando mapa parent-child...[/dim]")
        with open(parent_path, "r", encoding="utf-8") as f:
            _parent_map = json.load(f)
        console.print(
            f"[green]  Parent-child map: {len(_parent_map)} mapeamentos.[/green]"
        )
    else:
        _parent_map = {}

    # 6. Chunks by ID
    chunks_path = data_dir / "chunks.json"
    if chunks_path.exists():
        console.print("[dim]Carregando chunks...[/dim]")
        with open(chunks_path, "r", encoding="utf-8") as f:
            chunks_list = json.load(f)
        _chunks_by_id = {c["id"]: c for c in chunks_list}
        console.print(
            f"[green]  Chunks carregados: {len(_chunks_by_id)} documentos.[/green]"
        )
    else:
        console.print("[yellow]  chunks.json nao encontrado.[/yellow]")
        _chunks_by_id = {}

    console.print("[bold green]Sistema hibrido pronto![/bold green]\n")
    return _model, _collection


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _resolver_texto_chunk(chunk_id: str) -> str | None:
    """Return chunk text by id."""
    chunk = _chunks_by_id.get(chunk_id)
    if chunk is None:
        return None
    return chunk.get("texto")
