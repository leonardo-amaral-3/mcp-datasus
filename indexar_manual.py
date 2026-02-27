"""
Indexa os chunks do manual num banco vetorial ChromaDB
usando embeddings multilíngue (português).

Também constrói índice BM25 para busca híbrida.
"""

import json
import pickle
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer


def construir_bm25(chunks: list[dict], data_dir: Path):
    """Constrói índice BM25 a partir dos child chunks e salva em disco."""
    try:
        from busca_hibrida import tokenizar_pt
    except ImportError:
        print("  Aviso: busca_hibrida.py não encontrado, pulando índice BM25.")
        return

    from rank_bm25 import BM25Okapi

    corpus = [tokenizar_pt(c["contexto"]) for c in chunks]
    ids = [c["id"] for c in chunks]
    metadatas = [
        {
            "secao": c["secao"],
            "titulo": c["titulo"],
            "pagina": c["pagina"],
            "fonte": c.get("fonte", ""),
            "ano": c.get("ano", ""),
            "tipo": c.get("tipo", ""),
        }
        for c in chunks
    ]

    bm25 = BM25Okapi(corpus)

    bm25_path = data_dir / "bm25_index.pkl"
    with open(bm25_path, "wb") as f:
        pickle.dump({"bm25": bm25, "ids": ids, "metadatas": metadatas}, f)

    print(f"  Índice BM25: {len(ids)} documentos -> {bm25_path}")


def main():
    data_dir = Path(__file__).parent / "data"
    db_dir = Path(__file__).parent / "db"

    chunks_path = data_dir / "chunks.json"
    if not chunks_path.exists():
        print("Erro: Execute primeiro 'python extrair_manual.py' para gerar os chunks.")
        sys.exit(1)

    with open(chunks_path, encoding="utf-8") as f:
        all_chunks = json.load(f)

    # Filtrar: só indexar child chunks (is_parent=False ou campo ausente)
    child_chunks = [c for c in all_chunks if not c.get("is_parent", False)]
    parent_chunks = [c for c in all_chunks if c.get("is_parent", False)]

    print(f"Carregando {len(all_chunks)} chunks ({len(child_chunks)} children, {len(parent_chunks)} parents)...")

    # Modelo multilíngue que entende bem português
    print("Carregando modelo de embeddings (primeira vez pode demorar ~500MB)...")
    model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

    print(f"Gerando embeddings para {len(child_chunks)} child chunks...")
    textos = [c["contexto"] for c in child_chunks]
    embeddings = model.encode(textos, show_progress_bar=True, normalize_embeddings=True)

    # Criar banco vetorial
    print("Indexando no ChromaDB...")
    db_dir.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(db_dir))

    # Recriar collection se já existir
    try:
        client.delete_collection("manual_sih")
    except Exception:
        pass

    collection = client.create_collection(
        name="manual_sih",
        metadata={"hnsw:space": "cosine"},
    )

    # Inserir child chunks
    collection.add(
        ids=[c["id"] for c in child_chunks],
        embeddings=[e.tolist() for e in embeddings],
        documents=[c["contexto"] for c in child_chunks],
        metadatas=[
            {
                "secao": c["secao"],
                "titulo": c["titulo"],
                "pagina": c["pagina"],
                "fonte": c.get("fonte", "Manual SIH/SUS"),
                "ano": c.get("ano", ""),
                "tipo": c.get("tipo", "manual"),
            }
            for c in child_chunks
        ],
    )

    # Construir índice BM25
    print("Construindo índice BM25...")
    construir_bm25(child_chunks, data_dir)

    # Resumo por fonte
    fontes = {}
    for c in child_chunks:
        fonte = c.get("fonte", "Manual SIH/SUS")
        fontes[fonte] = fontes.get(fonte, 0) + 1

    print(f"\nIndexação completa!")
    print(f"  {collection.count()} child chunks indexados no ChromaDB")
    if parent_chunks:
        print(f"  {len(parent_chunks)} parent chunks disponíveis para contexto")
    for fonte, qtd in sorted(fontes.items()):
        print(f"  - {fonte}: {qtd} chunks")
    print(f"  Banco salvo em: {db_dir}")
    print(f"\nAgora execute: python consulta_manual.py")


if __name__ == "__main__":
    main()
