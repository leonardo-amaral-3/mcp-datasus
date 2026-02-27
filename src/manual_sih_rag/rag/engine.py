"""Core RAG engine — carregar_sistema() and buscar().

These are the primary entry points used by the MCP server and CLI.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from .hints import CRITICA_HINTS
from .paths import DB_DIR


def carregar_sistema() -> tuple[SentenceTransformer, Any]:
    """Load embedding model and vector store (tries hybrid first)."""
    chroma_host = os.getenv("CHROMA_HOST")

    if not chroma_host and not DB_DIR.exists():
        print(
            "Erro: Banco vetorial nao encontrado. Execute primeiro:\n"
            "  python extrair_manual.py\n"
            "  python indexar_manual.py",
            file=sys.stderr,
        )
        sys.exit(1)

    # Try hybrid system first
    try:
        from .hybrid_search import carregar_sistema_hibrido

        model, collection = carregar_sistema_hibrido()
        return model, collection
    except (ImportError, Exception):
        pass

    # Fallback: original system
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    if chroma_host:
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    else:
        client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection("manual_sih")

    return model, collection


def buscar(
    pergunta: str,
    model: SentenceTransformer,
    collection: Any,
    n_resultados: int = 5,
) -> list[dict]:
    """Search for relevant manual excerpts. Tries hybrid, falls back to vector."""
    # Try hybrid search
    try:
        from .hybrid_search import buscar_hibrida, _bm25

        if _bm25 is not None:
            return buscar_hibrida(pergunta, model, collection, n_resultados)
    except (ImportError, Exception):
        pass

    # Fallback: vector-only search
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
        items.append({
            "id": resultados["ids"][0][i],
            "texto": resultados["documents"][0][i],
            "metadata": resultados["metadatas"][0][i],
            "score": 1 - resultados["distances"][0][i],
        })

    return items
