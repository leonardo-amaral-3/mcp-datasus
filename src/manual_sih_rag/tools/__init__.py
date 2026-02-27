"""MCP tools para auditoria de faturamento hospitalar."""

from __future__ import annotations

import json
from typing import Any


def _json(data: Any) -> str:
    """Serializa para JSON sem ASCII escape."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _erro(msg: str) -> str:
    return _json({"erro": msg})


def _resolver_comp(client: Any, competencia: str, fonte: str = "SIGTAP") -> str:
    """Resolve competencia: usa a fornecida ou busca a mais recente."""
    if competencia:
        return competencia
    return client.ultima_competencia(fonte)
