"""
Pipeline de busca hibrida para o Manual Tecnico SIH/SUS.

Combina BM25 + Busca Vetorial + Reranker + Parent-Child + Query Decomposition
+ Metadata Filtering para melhorar a recuperacao de trechos relevantes.

Fornece drop-in replacements para:
  - consulta_manual.buscar()   -> buscar_hibrida()
  - validar_critica.buscar_manual() -> buscar_manual_hibrida()
"""

import json
import pickle
import re
import unicodedata
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi
from rich.console import Console
from sentence_transformers import CrossEncoder, SentenceTransformer

console = Console()

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
_CRITICA_HINTS: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Portuguese stopwords
# ---------------------------------------------------------------------------
_PT_STOPWORDS = frozenset(
    "a o e de do da dos das em no na nos nas um uma uns umas para por com como "
    "que se ou ao aos as os seu sua seus suas este esta esse essa isso isto "
    "aquele aquela ser ter estar foi sao nao mais muito bem ja so entre ate "
    "sobre quando qual quais cada todo toda todos todas pode deve tambem mesmo "
    "ainda pela pelo pelos pelas num numa".split()
)


# ---------------------------------------------------------------------------
# 1. tokenizar_pt
# ---------------------------------------------------------------------------
def tokenizar_pt(texto: str) -> list[str]:
    """Tokeniza texto em portugues: lowercase, sem acentos, sem stopwords."""
    texto = texto.lower()
    # Remove accents via NFD decomposition
    nfkd = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    # Remove non-alphanum (keep spaces)
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    tokens = texto.split()
    return [t for t in tokens if len(t) >= 2 and t not in _PT_STOPWORDS]


# ---------------------------------------------------------------------------
# 2. extrair_filtros_metadata
# ---------------------------------------------------------------------------
def extrair_filtros_metadata(pergunta: str) -> dict | None:
    """Detecta filtros de metadata a partir da pergunta do usuario."""
    pergunta_lower = pergunta.lower()
    filtros: list[dict] = []

    # Year detection (20XX)
    m_ano = re.search(r"\b(20\d{2})\b", pergunta)
    if m_ano:
        filtros.append({"ano": m_ano.group(1)})

    # Type detection
    tem_portaria = bool(re.search(r"\bportaria\b", pergunta_lower))
    tem_manual = bool(re.search(r"\bmanual\b", pergunta_lower))
    # Only filter by "anexo_sigtap" when user explicitly asks for "anexo sigtap"
    # or "tabela sigtap", not just mentions "sigtap" as a concept
    tem_anexo_sigtap = bool(re.search(r"\b(anexo\s+sigtap|tabela\s+sigtap)\b", pergunta_lower))

    if tem_anexo_sigtap:
        filtros.append({"tipo": "anexo_sigtap"})
    elif tem_portaria and not tem_manual:
        filtros.append({"tipo": "portaria"})
    elif tem_manual and not tem_portaria:
        filtros.append({"tipo": "manual"})

    if not filtros:
        return None
    if len(filtros) == 1:
        return filtros[0]
    return {"$and": filtros}


# ---------------------------------------------------------------------------
# 3. decompor_query
# ---------------------------------------------------------------------------
def decompor_query(pergunta: str) -> list[str]:
    """Decompoe a pergunta em sub-queries para busca mais abrangente."""
    queries: list[str] = [pergunta]

    # CRITICA_HINTS enrichment
    pergunta_lower = pergunta.lower().strip()
    for chave, hint in _CRITICA_HINTS.items():
        if chave in pergunta_lower:
            queries.append(f"{pergunta} {hint}")
            break

    # Split on " e " if both parts have >= 2 words
    if " e " in pergunta:
        partes = pergunta.split(" e ", 1)
        if len(partes[0].split()) >= 2 and len(partes[1].split()) >= 2:
            queries.append(partes[0].strip())
            queries.append(partes[1].strip())

    # "diferenca entre X e Y" pattern
    m_diff = re.search(
        r"diferen[cç]a\s+entre\s+(.+?)\s+e\s+(.+)",
        pergunta,
        re.IGNORECASE,
    )
    if m_diff:
        queries.append(m_diff.group(1).strip())
        queries.append(m_diff.group(2).strip())

    # Abbreviation expansion
    _abreviacoes = {
        "opm": "orteses proteses materiais especiais OPM",
        "cid": "classificacao internacional doencas CID diagnostico",
        "cbo": "classificacao brasileira ocupacoes CBO profissional",
        "cnes": "cadastro nacional estabelecimentos saude CNES",
        "uti": "unidade terapia intensiva UTI leito",
        "aih": "autorizacao internacao hospitalar AIH",
    }
    for sigla, expansao in _abreviacoes.items():
        if re.search(rf"\b{sigla}\b", pergunta_lower):
            queries.append(f"{pergunta} {expansao}")
            break

    # Deduplicate preserving order
    vistos: set[str] = set()
    dedup: list[str] = []
    for q in queries:
        q_norm = q.strip()
        if q_norm and q_norm not in vistos:
            vistos.add(q_norm)
            dedup.append(q_norm)

    return dedup if dedup else [pergunta]


# ---------------------------------------------------------------------------
# 4. buscar_bm25
# ---------------------------------------------------------------------------
def buscar_bm25(
    pergunta: str,
    n_resultados: int = 20,
    where: dict | None = None,
) -> list[tuple[str, float]]:
    """Busca BM25 sobre os chunks indexados."""
    if _bm25 is None:
        return []

    tokens = tokenizar_pt(pergunta)
    if not tokens:
        return []

    scores = _bm25.get_scores(tokens)

    candidatos: list[tuple[str, float]] = []
    for idx, score in enumerate(scores):
        if score <= 0:
            continue
        if idx >= len(_bm25_ids):
            continue
        chunk_id = _bm25_ids[idx]
        if where is not None:
            meta = _bm25_metadatas[idx] if idx < len(_bm25_metadatas) else {}
            if not _match_filter(meta, where):
                continue
        candidatos.append((chunk_id, float(score)))

    candidatos.sort(key=lambda x: x[1], reverse=True)
    return candidatos[:n_resultados]


# ---------------------------------------------------------------------------
# 5. _match_filter
# ---------------------------------------------------------------------------
def _match_filter(meta: dict, where: dict) -> bool:
    """Verifica se metadata bate com o filtro (suporte a $and)."""
    if "$and" in where:
        return all(_match_filter(meta, sub) for sub in where["$and"])
    for key, value in where.items():
        if str(meta.get(key, "")) != str(value):
            return False
    return True


# ---------------------------------------------------------------------------
# 6. buscar_vetorial
# ---------------------------------------------------------------------------
def buscar_vetorial(
    pergunta: str,
    n_resultados: int = 20,
    where: dict | None = None,
) -> list[tuple[str, float]]:
    """Busca vetorial via SentenceTransformer + ChromaDB."""
    if _model is None or _collection is None:
        return []

    embedding = _model.encode([pergunta], normalize_embeddings=True)

    kwargs: dict[str, Any] = {
        "query_embeddings": [embedding[0].tolist()],
        "n_results": n_resultados,
        "include": ["distances"],
    }
    if where is not None:
        kwargs["where"] = where

    try:
        resultado = _collection.query(**kwargs)
    except Exception:
        # Fallback without where filter if ChromaDB rejects it
        kwargs.pop("where", None)
        resultado = _collection.query(**kwargs)

    items: list[tuple[str, float]] = []
    for i in range(len(resultado["ids"][0])):
        chunk_id = resultado["ids"][0][i]
        distance = resultado["distances"][0][i]
        items.append((chunk_id, 1.0 - distance))

    return items


# ---------------------------------------------------------------------------
# 7. reciprocal_rank_fusion
# ---------------------------------------------------------------------------
def reciprocal_rank_fusion(
    *ranked_lists: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: score(d) = SUM(1 / (k + rank_i))."""
    rrf_scores: dict[str, float] = {}

    for rlist in ranked_lists:
        for rank_0, (doc_id, _score) in enumerate(rlist):
            rank = rank_0 + 1  # 1-based
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    merged = [(doc_id, score) for doc_id, score in rrf_scores.items()]
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


# ---------------------------------------------------------------------------
# 8. rerancar
# ---------------------------------------------------------------------------
def rerancar(
    pergunta: str,
    candidatos: list[tuple[str, float]],
    top_n: int = 10,
) -> list[tuple[str, float]]:
    """Reranqueia candidatos usando CrossEncoder."""
    if _reranker is None or not candidatos:
        return candidatos[:top_n]

    pairs: list[tuple[str, str]] = []
    valid_ids: list[str] = []
    for chunk_id, _score in candidatos:
        texto = _resolver_texto_chunk(chunk_id)
        if texto:
            pairs.append((pergunta, texto))
            valid_ids.append(chunk_id)

    if not pairs:
        return candidatos[:top_n]

    scores = _reranker.predict(pairs)

    reranked = list(zip(valid_ids, [float(s) for s in scores]))
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:top_n]


# ---------------------------------------------------------------------------
# 9. _resolver_texto_chunk
# ---------------------------------------------------------------------------
def _resolver_texto_chunk(chunk_id: str) -> str | None:
    """Retorna o texto de um chunk pelo seu id."""
    chunk = _chunks_by_id.get(chunk_id)
    if chunk is None:
        return None
    return chunk.get("texto")


# ---------------------------------------------------------------------------
# 10. resolver_parent_chunks
# ---------------------------------------------------------------------------
def resolver_parent_chunks(
    resultados: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """Mapeia child chunks para parent chunks, deduplicando."""
    parent_scores: dict[str, float] = {}

    for child_id, score in resultados:
        parent_id = _parent_map.get(child_id, child_id)
        if parent_id not in parent_scores or score > parent_scores[parent_id]:
            parent_scores[parent_id] = score

    merged = [(pid, sc) for pid, sc in parent_scores.items()]
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged


# ---------------------------------------------------------------------------
# 11. pipeline_busca
# ---------------------------------------------------------------------------
def pipeline_busca(
    pergunta: str,
    n_resultados: int = 5,
    usar_reranker: bool = True,
    usar_decomposicao: bool = True,
    usar_parent: bool = True,
    where: dict | None = None,
) -> list[tuple[str, float, dict]]:
    """Pipeline completo: decomposicao + BM25 + vetorial + RRF + reranker + parent."""
    # Auto-extract metadata filters
    if where is None:
        where = extrair_filtros_metadata(pergunta)

    # Decompose query
    if usar_decomposicao:
        sub_queries = decompor_query(pergunta)
    else:
        sub_queries = [pergunta]

    # Collect BM25 and vector results for each sub-query
    all_bm25: list[tuple[str, float]] = []
    all_vec: list[tuple[str, float]] = []

    for sq in sub_queries:
        all_bm25.extend(buscar_bm25(sq, n_resultados=20, where=where))
        all_vec.extend(buscar_vetorial(sq, n_resultados=20, where=where))

    # RRF fusion
    fused = reciprocal_rank_fusion(all_bm25, all_vec, k=60)

    # Rerank (skip for very short/numeric queries where BM25 is more reliable)
    palavras = pergunta.strip().split()
    query_curta = len(palavras) <= 2 or pergunta.strip().isdigit()
    if usar_reranker and not query_curta:
        top_rerank = max(20, n_resultados * 3)
        reranked = rerancar(pergunta, fused[:top_rerank], top_n=n_resultados * 2)
    else:
        reranked = fused[: n_resultados * 2]

    # Resolve parents
    if usar_parent and _parent_map:
        reranked = resolver_parent_chunks(reranked)

    # Build final results with metadata
    final: list[tuple[str, float, dict]] = []
    for chunk_id, score in reranked:
        chunk = _chunks_by_id.get(chunk_id)
        if chunk is None:
            continue
        meta = {
            k: v
            for k, v in chunk.items()
            if k not in ("texto", "contexto")
        }
        final.append((chunk_id, score, meta))

    return final[:n_resultados]


# ---------------------------------------------------------------------------
# 12. buscar_hibrida  (drop-in for consulta_manual.buscar)
# ---------------------------------------------------------------------------
def buscar_hibrida(
    pergunta: str,
    model: SentenceTransformer,
    collection: Any,
    n_resultados: int = 5,
) -> list[dict]:
    """
    Drop-in replacement para consulta_manual.buscar().

    Retorna EXATAMENTE:
    [{"id": str, "texto": str, "metadata": {"secao": str, "titulo": str, "pagina": int}, "score": float}]
    """
    resultados = pipeline_busca(pergunta, n_resultados=n_resultados)

    items: list[dict] = []
    for chunk_id, score, meta in resultados:
        texto = _resolver_texto_chunk(chunk_id) or ""

        # Strip "[Manual..." prefix
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

        items.append(
            {
                "id": str(chunk_id),
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


# ---------------------------------------------------------------------------
# 13. buscar_manual_hibrida  (drop-in for validar_critica.buscar_manual)
# ---------------------------------------------------------------------------
def buscar_manual_hibrida(
    queries: list[str],
    model: SentenceTransformer,
    collection: Any,
    n_por_query: int = 3,
) -> list[dict]:
    """
    Drop-in replacement para validar_critica.buscar_manual().

    Retorna EXATAMENTE:
    [{"id": str, "secao": str, "titulo": str, "pagina": int,
      "texto": str, "relevancia": float, "query_origem": str}]
    """
    todos: dict[str, dict] = {}

    for query in queries:
        resultados = pipeline_busca(
            query,
            n_resultados=n_por_query,
            usar_decomposicao=False,
        )
        for chunk_id, score, meta in resultados:
            if chunk_id not in todos or score > todos[chunk_id]["relevancia"]:
                texto = _resolver_texto_chunk(chunk_id) or ""

                # Strip "[Manual..." prefix
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
# 14. carregar_sistema_hibrido
# ---------------------------------------------------------------------------
def carregar_sistema_hibrido(
    db_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    carregar_reranker: bool = True,
) -> tuple[SentenceTransformer, Any]:
    """
    Carrega todos os componentes do sistema hibrido.

    Retorna (model, collection) para backward compat.
    """
    global _model, _collection, _bm25, _reranker
    global _bm25_ids, _bm25_metadatas, _parent_map, _chunks_by_id, _CRITICA_HINTS

    base = Path(__file__).parent
    if db_dir is None:
        db_dir = base / "db"
    else:
        db_dir = Path(db_dir)
    if data_dir is None:
        data_dir = base / "data"
    else:
        data_dir = Path(data_dir)

    # 1. SentenceTransformer
    console.print("[dim]Carregando modelo de embeddings...[/dim]")
    _model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    console.print("[green]  Modelo de embeddings carregado.[/green]")

    # 2. ChromaDB collection
    import chromadb
    import os as _os

    console.print("[dim]Conectando ao banco vetorial...[/dim]")
    chroma_host = _os.getenv("CHROMA_HOST")
    if chroma_host:
        chroma_port = int(_os.getenv("CHROMA_PORT", "8000"))
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    else:
        client = chromadb.PersistentClient(path=str(db_dir))
    _collection = client.get_collection("manual_sih")
    console.print(
        f"[green]  Banco vetorial conectado: {_collection.count()} chunks.[/green]"
    )

    # 3. BM25 index (graceful if missing)
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
        console.print("[yellow]  BM25 index nao encontrado (bm25_index.pkl). Busca BM25 desabilitada.[/yellow]")
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

    # 7. CRITICA_HINTS from consulta_manual
    try:
        from consulta_manual import CRITICA_HINTS

        _CRITICA_HINTS = dict(CRITICA_HINTS)
        console.print(
            f"[green]  CRITICA_HINTS importados: {len(_CRITICA_HINTS)} entradas.[/green]"
        )
    except ImportError:
        _CRITICA_HINTS = {}

    console.print("[bold green]Sistema hibrido pronto![/bold green]\n")
    return _model, _collection
