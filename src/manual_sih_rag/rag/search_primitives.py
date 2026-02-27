"""Pure search functions: tokenizer, BM25, vector, RRF, reranker.

These are stateless functions that receive all dependencies as arguments.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .hints import CRITICA_HINTS

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
    """Tokenize Portuguese text: lowercase, no accents, no stopwords."""
    texto = texto.lower()
    nfkd = unicodedata.normalize("NFD", texto)
    texto = "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    tokens = texto.split()
    return [t for t in tokens if len(t) >= 2 and t not in _PT_STOPWORDS]


# ---------------------------------------------------------------------------
# 2. extrair_filtros_metadata
# ---------------------------------------------------------------------------
def extrair_filtros_metadata(pergunta: str) -> dict | None:
    """Detect metadata filters from the user query."""
    pergunta_lower = pergunta.lower()
    filtros: list[dict] = []

    m_ano = re.search(r"\b(20\d{2})\b", pergunta)
    if m_ano:
        filtros.append({"ano": m_ano.group(1)})

    tem_portaria = bool(re.search(r"\bportaria\b", pergunta_lower))
    tem_manual = bool(re.search(r"\bmanual\b", pergunta_lower))
    tem_anexo_sigtap = bool(
        re.search(r"\b(anexo\s+sigtap|tabela\s+sigtap)\b", pergunta_lower)
    )

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
def decompor_query(pergunta: str, critica_hints: dict[str, str] | None = None) -> list[str]:
    """Decompose a query into sub-queries for broader retrieval."""
    if critica_hints is None:
        critica_hints = CRITICA_HINTS

    queries: list[str] = [pergunta]

    pergunta_lower = pergunta.lower().strip()
    for chave, hint in critica_hints.items():
        if chave in pergunta_lower:
            queries.append(f"{pergunta} {hint}")
            break

    if " e " in pergunta:
        partes = pergunta.split(" e ", 1)
        if len(partes[0].split()) >= 2 and len(partes[1].split()) >= 2:
            queries.append(partes[0].strip())
            queries.append(partes[1].strip())

    m_diff = re.search(
        r"diferen[cç]a\s+entre\s+(.+?)\s+e\s+(.+)", pergunta, re.IGNORECASE,
    )
    if m_diff:
        queries.append(m_diff.group(1).strip())
        queries.append(m_diff.group(2).strip())

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
    bm25: Any,
    bm25_ids: list[str],
    bm25_metadatas: list[dict],
    n_resultados: int = 20,
    where: dict | None = None,
) -> list[tuple[str, float]]:
    """BM25 search over indexed chunks."""
    if bm25 is None:
        return []

    tokens = tokenizar_pt(pergunta)
    if not tokens:
        return []

    scores = bm25.get_scores(tokens)

    candidatos: list[tuple[str, float]] = []
    for idx, score in enumerate(scores):
        if score <= 0:
            continue
        if idx >= len(bm25_ids):
            continue
        chunk_id = bm25_ids[idx]
        if where is not None:
            meta = bm25_metadatas[idx] if idx < len(bm25_metadatas) else {}
            if not _match_filter(meta, where):
                continue
        candidatos.append((chunk_id, float(score)))

    candidatos.sort(key=lambda x: x[1], reverse=True)
    return candidatos[:n_resultados]


# ---------------------------------------------------------------------------
# 5. _match_filter
# ---------------------------------------------------------------------------
def _match_filter(meta: dict, where: dict) -> bool:
    """Check if metadata matches filter (supports $and)."""
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
    model: Any,
    collection: Any,
    n_resultados: int = 20,
    where: dict | None = None,
) -> list[tuple[str, float]]:
    """Vector search via SentenceTransformer + ChromaDB."""
    if model is None or collection is None:
        return []

    embedding = model.encode([pergunta], normalize_embeddings=True)

    kwargs: dict[str, Any] = {
        "query_embeddings": [embedding[0].tolist()],
        "n_results": n_resultados,
        "include": ["distances"],
    }
    if where is not None:
        kwargs["where"] = where

    try:
        resultado = collection.query(**kwargs)
    except Exception:
        kwargs.pop("where", None)
        resultado = collection.query(**kwargs)

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
    """RRF: score(d) = SUM(1 / (k + rank_i))."""
    rrf_scores: dict[str, float] = {}

    for rlist in ranked_lists:
        for rank_0, (doc_id, _score) in enumerate(rlist):
            rank = rank_0 + 1
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
    chunks_by_id: dict[str, dict],
    reranker: Any | None = None,
    top_n: int = 10,
) -> list[tuple[str, float]]:
    """Rerank candidates using CrossEncoder."""
    if reranker is None or not candidatos:
        return candidatos[:top_n]

    pairs: list[tuple[str, str]] = []
    valid_ids: list[str] = []
    for chunk_id, _score in candidatos:
        chunk = chunks_by_id.get(chunk_id)
        if chunk and chunk.get("texto"):
            pairs.append((pergunta, chunk["texto"]))
            valid_ids.append(chunk_id)

    if not pairs:
        return candidatos[:top_n]

    scores = reranker.predict(pairs)

    reranked = list(zip(valid_ids, [float(s) for s in scores]))
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked[:top_n]


# ---------------------------------------------------------------------------
# 9. resolver_parent_chunks
# ---------------------------------------------------------------------------
def resolver_parent_chunks(
    resultados: list[tuple[str, float]],
    parent_map: dict[str, str],
) -> list[tuple[str, float]]:
    """Map child chunks to parent chunks, deduplicating."""
    parent_scores: dict[str, float] = {}

    for child_id, score in resultados:
        parent_id = parent_map.get(child_id, child_id)
        if parent_id not in parent_scores or score > parent_scores[parent_id]:
            parent_scores[parent_id] = score

    merged = [(pid, sc) for pid, sc in parent_scores.items()]
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged
