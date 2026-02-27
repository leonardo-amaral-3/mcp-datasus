"""Backward-compat wrapper — real code in manual_sih_rag.rag.

Delegates to:
  - manual_sih_rag.rag.hybrid_search  (stateful pipeline)
  - manual_sih_rag.rag.search_primitives  (pure functions)

Module-level globals (_bm25, _model, etc.) are forwarded via PEP 562
__getattr__ to the canonical location in hybrid_search.
"""

import manual_sih_rag.rag.hybrid_search as _hs

from manual_sih_rag.rag.hybrid_search import (  # noqa: F401
    buscar_hibrida,
    buscar_manual_hibrida,
    carregar_sistema_hibrido,
    pipeline_busca,
)
from manual_sih_rag.rag.search_primitives import tokenizar_pt  # noqa: F401

# PEP 562: forward mutable module-level globals to hybrid_search
_FORWARDED = frozenset({
    "_model", "_collection", "_bm25", "_reranker",
    "_bm25_ids", "_bm25_metadatas", "_parent_map", "_chunks_by_id",
})


def __getattr__(name: str):
    if name in _FORWARDED:
        return getattr(_hs, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
