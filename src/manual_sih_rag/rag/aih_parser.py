"""AIH text parser — extracts structured data from AIH mirror text."""

from __future__ import annotations

import re


def ler_texto_multilinhas() -> str:
    """Read multiline input until user types /fim."""
    linhas = []
    while True:
        try:
            linha = input()
            if linha.strip().lower() == "/fim":
                break
            linhas.append(linha)
        except (EOFError, KeyboardInterrupt):
            break
    return "\n".join(linhas)


def extrair_dados_aih(texto: str) -> dict:
    """Extract structured data from an AIH mirror text."""
    dados: dict = {
        "num_aih": None,
        "procedimento_principal": None,
        "diagnostico_principal": None,
        "cids_secundarios": [],
        "procedimentos_unicos": [],
        "especialidade": None,
        "carater": None,
        "motivo_saida": None,
        "tipo": None,
    }

    # Num AIH
    m = re.search(r"Num\s+AIH\s*:\s*([\d-]+)", texto)
    if m:
        dados["num_aih"] = m.group(1).strip()

    # Tipo
    m = re.search(r"Tipo\s*:\s*\d+-(\S+)", texto)
    if m:
        dados["tipo"] = m.group(1).strip()

    # Procedimento principal: XX.XX.XX.XXX-X - NOME
    m = re.search(
        r"[Pp]rocedimento\s+principal\s*:\s*([\d.]+\d-\d)\s*-\s*(.+)", texto
    )
    if m:
        codigo = re.sub(r"[.\-]", "", m.group(1))
        dados["procedimento_principal"] = (codigo, m.group(2).strip())

    # Diagnostico principal
    m = re.search(r"[Dd]iag\.\s*principal\s*:\s*([A-Z]\d{2,4})\s*-?\s*(.*)", texto)
    if m:
        dados["diagnostico_principal"] = (m.group(1), m.group(2).strip())

    # Especialidade
    m = re.search(r"[Ee]specialidade\s*:\s*\d+\s*-\s*(.+)", texto)
    if m:
        dados["especialidade"] = m.group(1).strip()

    # Carater atendimento
    m = re.search(r"[Cc]arater\s+atendimento\s*:\s*\d+\s*-\s*(.+)", texto)
    if m:
        dados["carater"] = m.group(1).strip()

    # Motivo saida
    m = re.search(r"[Mm]ot\s*saida\s*:\s*\d+\s*-\s*(.+)", texto)
    if m:
        dados["motivo_saida"] = m.group(1).strip()

    # Procedimentos realizados (10 digitos comecando com 0)
    procs_vistos: set[str] = set()
    for m in re.finditer(r"\b(0[1-8]\d{8})\b", texto):
        cod = m.group(1)
        if cod not in procs_vistos:
            procs_vistos.add(cod)
            dados["procedimentos_unicos"].append(cod)

    # CIDs secundarios - secao especifica
    cid_section = re.search(
        r"CID\s+SECUND[ÁA]RIO(.*?)(?:CNPJ\s+Fabricante|MS-DATASUS|$)",
        texto,
        re.DOTALL | re.IGNORECASE,
    )
    if cid_section:
        for m in re.finditer(r"\b([A-Z]\d{3})\b", cid_section.group(1)):
            cid = m.group(1)
            if cid not in dados["cids_secundarios"]:
                dados["cids_secundarios"].append(cid)

    return dados
