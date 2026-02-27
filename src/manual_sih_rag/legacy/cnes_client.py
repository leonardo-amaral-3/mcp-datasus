"""CNES client — reads operational facility data from MinIO (Parquet).

Loads beds, services, qualifications and professionals on first call.
"""

from __future__ import annotations

from typing import Any

from .s3_client import ler_parquet, ultima_competencia

_leitos: dict[str, list[dict]] = {}
_servicos: dict[str, list[dict]] = {}
_habilitacoes: dict[str, list[str]] = {}
_profissionais: dict[str, list[dict]] = {}
_competencia: str = ""
_carregado = False


def _agrupar_por_cnes(tabela: Any, colunas_extra: list[str]) -> dict[str, list[dict]]:
    """Group rows of a pyarrow table by 'cnes' column."""
    resultado: dict[str, list[dict]] = {}
    col_names = tabela.column_names
    for i in range(tabela.num_rows):
        cnes = str(tabela.column("cnes")[i].as_py()).strip()
        row = {col: tabela.column(col)[i].as_py() for col in colunas_extra if col in col_names}
        resultado.setdefault(cnes, []).append(row)
    return resultado


def _carregar(competencia: str | None = None) -> None:
    global _leitos, _servicos, _habilitacoes, _profissionais, _competencia, _carregado
    if _carregado:
        return

    comp = competencia or ultima_competencia("CNES")
    if not comp:
        raise RuntimeError("Nenhuma competencia CNES encontrada no MinIO.")

    _competencia = comp
    prefixo = f"CNES/{comp}"

    t = ler_parquet(f"{prefixo}/leitos.parquet")
    if t is not None:
        _leitos = _agrupar_por_cnes(t, ["co_leito", "co_tipo_leito", "quantidade_sus"])

    t = ler_parquet(f"{prefixo}/servicos.parquet")
    if t is not None:
        _servicos = _agrupar_por_cnes(t, ["co_servico", "co_classificacao", "tp_caracteristica"])

    t = ler_parquet(f"{prefixo}/habilitacoes.parquet")
    if t is not None:
        hab: dict[str, list[str]] = {}
        for i in range(t.num_rows):
            cnes = str(t.column("cnes")[i].as_py()).strip()
            cod = str(t.column("cod_sub_grupo_habilitacao")[i].as_py()).strip()
            hab.setdefault(cnes, []).append(cod)
        _habilitacoes = hab

    t = ler_parquet(f"{prefixo}/profissionais.parquet")
    if t is not None:
        _profissionais = _agrupar_por_cnes(
            t, ["co_ocupacao", "co_profissional_sus", "qt_carga_horaria_total_profissional"]
        )

    _carregado = True


def consultar_cnes(codigo: str) -> dict | None:
    """Return aggregated data for a CNES (beds, services, qualifications, professionals)."""
    _carregar()
    codigo = codigo.strip()

    leitos = _leitos.get(codigo, [])
    servicos = _servicos.get(codigo, [])
    habs = _habilitacoes.get(codigo, [])
    profs = _profissionais.get(codigo, [])

    if not any([leitos, servicos, habs, profs]):
        return None

    ocupacoes: dict[str, int] = {}
    for p in profs:
        oc = str(p.get("co_ocupacao", "?"))
        ocupacoes[oc] = ocupacoes.get(oc, 0) + 1

    return {
        "cnes": codigo,
        "competencia": _competencia,
        "leitos": leitos,
        "total_leitos_sus": sum(int(l.get("quantidade_sus", 0) or 0) for l in leitos),
        "servicos": servicos,
        "habilitacoes": habs,
        "profissionais_por_ocupacao": ocupacoes,
        "total_profissionais": len(profs),
    }


def buscar_profissionais(cnes: str, co_ocupacao: str = "") -> list[dict]:
    """List professionals for a CNES, with optional occupation filter."""
    _carregar()
    profs = _profissionais.get(cnes.strip(), [])
    if co_ocupacao:
        profs = [p for p in profs if str(p.get("co_ocupacao", "")) == co_ocupacao]
    return profs


def info() -> dict:
    """Return CNES metadata."""
    _carregar()
    return {
        "competencia": _competencia,
        "total_cnes_com_leitos": len(_leitos),
        "total_cnes_com_servicos": len(_servicos),
        "total_cnes_com_habilitacoes": len(_habilitacoes),
        "total_cnes_com_profissionais": len(_profissionais),
    }
