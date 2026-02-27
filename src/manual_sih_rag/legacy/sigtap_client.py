"""SIGTAP client — reads procedures and groups from MinIO (Parquet).

Loads tb_procedimento and tb_grupo on first call and keeps in memory.
"""

from __future__ import annotations

import unicodedata

from .s3_client import ler_parquet, ultima_competencia

_procedimentos: dict[str, dict] = {}
_grupos: dict[str, str] = {}
_competencia: str = ""
_carregado = False


def _normalizar(texto: str) -> str:
    texto = texto.lower()
    nfkd = unicodedata.normalize("NFD", texto)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")


def _carregar(competencia: str | None = None) -> None:
    global _procedimentos, _grupos, _competencia, _carregado
    if _carregado:
        return

    comp = competencia or ultima_competencia("SIGTAP")
    if not comp:
        raise RuntimeError("Nenhuma competencia SIGTAP encontrada no MinIO.")

    _competencia = comp
    prefixo = f"SIGTAP/{comp}"

    tabela = ler_parquet(f"{prefixo}/tb_procedimento.parquet")
    if tabela is None:
        raise RuntimeError(f"tb_procedimento.parquet nao encontrado em {prefixo}/")

    colunas = tabela.column_names
    for i in range(tabela.num_rows):
        row = {col: tabela.column(col)[i].as_py() for col in colunas}
        codigo = str(row.get("co_procedimento", "")).strip()
        if codigo:
            _procedimentos[codigo] = row

    tabela_g = ler_parquet(f"{prefixo}/tb_grupo.parquet")
    if tabela_g is not None:
        for i in range(tabela_g.num_rows):
            co = str(tabela_g.column("co_grupo")[i].as_py()).strip()
            no = str(tabela_g.column("no_grupo")[i].as_py()).strip()
            _grupos[co] = no

    _carregado = True


def consultar_procedimento(codigo: str) -> dict | None:
    """Look up procedure by code."""
    _carregar()
    codigo = codigo.strip()
    proc = _procedimentos.get(codigo) or _procedimentos.get(codigo.lstrip("0"))
    if not proc:
        return None
    codigo = str(proc.get("co_procedimento", codigo))

    return {
        "codigo": codigo,
        "nome": proc.get("no_procedimento", ""),
        "vl_sh": proc.get("vl_sh"),
        "vl_sa": proc.get("vl_sa"),
        "vl_sp": proc.get("vl_sp"),
        "vl_total_hospitalar": proc.get("vl_total_hospitalar"),
        "competencia": _competencia,
        **{k: v for k, v in proc.items() if k.startswith(("qt_", "id_", "tp_"))},
    }


def buscar_procedimentos(termo: str, grupo: str = "", limit: int = 20) -> list[dict]:
    """Search procedures by name (normalized). Optional group filter."""
    _carregar()
    termo_n = _normalizar(termo)
    resultados = []

    for codigo, proc in _procedimentos.items():
        nome_n = proc.get("no_procedimento_normalizado") or _normalizar(
            proc.get("no_procedimento", "")
        )
        if termo_n not in nome_n:
            continue
        if grupo and not codigo.startswith(grupo):
            continue
        resultados.append({
            "codigo": codigo,
            "nome": proc.get("no_procedimento", ""),
            "vl_total_hospitalar": proc.get("vl_total_hospitalar"),
        })
        if len(resultados) >= limit:
            break

    return resultados


def info() -> dict:
    """Return SIGTAP metadata."""
    _carregar()
    return {
        "competencia": _competencia,
        "total_procedimentos": len(_procedimentos),
        "grupos": [{"codigo": k, "nome": v} for k, v in sorted(_grupos.items())],
    }
