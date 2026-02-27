"""Core PDF extraction: text extraction, section detection, and chunk creation.

Extracted from root extrair_manual.py — pure functions, no CLI.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pymupdf

EXTENSOES_SUPORTADAS = {".pdf", ".htm", ".html", ".doc", ".zip"}
MAX_PAGINAS_ANEXO = 10
MAX_CHARS_HTML = 50000


def extrair_texto_paginas(pdf_path: str, max_paginas: int = 0) -> list[dict]:
    """Extract text from each page of a PDF. max_paginas=0 means no limit."""
    doc = pymupdf.open(pdf_path)
    paginas = []
    limite = max_paginas if max_paginas > 0 else len(doc)
    for i, page in enumerate(doc):
        if i >= limite:
            break
        texto = page.get_text("text")
        if texto.strip():
            paginas.append({"pagina": i + 1, "texto": texto.strip()})
    doc.close()
    return paginas


def detectar_secoes(paginas: list[dict]) -> list[dict]:
    """Detect manual sections based on title patterns."""
    padrao_secao = re.compile(
        r'^(\d{1,2}(?:\.\d{1,2})?(?:\.\d{1,2})?)\s+'
        r'([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s\-/,\(\)\.]+)',
        re.MULTILINE,
    )

    secoes = []
    secao_atual = None
    texto_acumulado: list[str] = []

    for pagina_info in paginas:
        pagina = pagina_info["pagina"]
        texto = pagina_info["texto"]

        if texto.count("...") > 5:
            continue

        linhas = texto.split("\n")
        linhas_filtradas = []
        for linha in linhas:
            if "MANUAL TÉCNICO OPERACIONAL" in linha:
                continue
            if "SISTEMA DE INFORMAÇÃO HOSPITALAR" in linha:
                continue
            if re.match(r"^\s*SETEMBRO 2012\s*$", linha):
                continue
            linhas_filtradas.append(linha)

        linhas_juntadas = []
        i = 0
        while i < len(linhas_filtradas):
            linha = linhas_filtradas[i]
            stripped = linha.strip()

            numero_match = re.match(
                r'^(\d{1,2}(?:\.\d{1,2})?(?:\.\d{1,2})?)\s*\.?\s*$', stripped
            )
            if numero_match and i + 1 < len(linhas_filtradas):
                proxima = linhas_filtradas[i + 1].strip()
                if proxima and re.match(
                    r'^[A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s\-/,\(\)\.]+$',
                    proxima,
                ):
                    linhas_juntadas.append(f"{stripped.rstrip('.')} {proxima}")
                    i += 2
                    continue

            if re.match(r'^\s*\d{1,3}\s*$', stripped):
                i += 1
                continue

            linhas_juntadas.append(linha)
            i += 1

        texto_limpo = "\n".join(linhas_juntadas).strip()
        if not texto_limpo:
            continue

        matches = list(padrao_secao.finditer(texto_limpo))

        if matches:
            for mi, match in enumerate(matches):
                if secao_atual:
                    if mi == 0:
                        texto_antes = texto_limpo[: match.start()].strip()
                        if texto_antes:
                            texto_acumulado.append(texto_antes)
                    secao_atual["texto"] = "\n".join(texto_acumulado).strip()
                    if secao_atual["texto"]:
                        secoes.append(secao_atual)
                    texto_acumulado = []
                elif mi == 0:
                    texto_antes = texto_limpo[: match.start()].strip()
                    if texto_antes and pagina > 8:
                        secoes.append({
                            "numero": "0",
                            "titulo": "PREÂMBULO",
                            "pagina_inicio": pagina,
                            "texto": texto_antes,
                        })

                inicio_texto = match.end()
                if mi + 1 < len(matches):
                    fim_texto = matches[mi + 1].start()
                else:
                    fim_texto = len(texto_limpo)

                texto_secao = texto_limpo[inicio_texto:fim_texto].strip()
                secao_atual = {
                    "numero": match.group(1),
                    "titulo": match.group(2).strip().rstrip("."),
                    "pagina_inicio": pagina,
                }
                texto_acumulado = [texto_secao] if texto_secao else []
        else:
            if secao_atual:
                texto_acumulado.append(texto_limpo)

    if secao_atual:
        secao_atual["texto"] = "\n".join(texto_acumulado).strip()
        if secao_atual["texto"]:
            secoes.append(secao_atual)

    return secoes


def _dividir_com_overlap(texto: str, max_chars: int, overlap: int = 200) -> list[str]:
    """Split text into chunks with overlap between consecutive pieces."""
    if len(texto) <= max_chars:
        return [texto]

    paragrafos = texto.split("\n\n")
    chunks = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragrafos:
        if current_len + len(para) > max_chars and current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(chunk_text)

            overlap_parts: list[str] = []
            overlap_len = 0
            for p in reversed(current_parts):
                if overlap_len + len(p) > overlap:
                    break
                overlap_parts.insert(0, p)
                overlap_len += len(p)

            current_parts = overlap_parts + [para]
            current_len = overlap_len + len(para)
        else:
            current_parts.append(para)
            current_len += len(para)

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def criar_chunks(
    secoes: list[dict],
    fonte: str = "Manual SIH/SUS",
    max_chars: int = 1500,
    ano: str = "",
    tipo: str = "manual",
    overlap: int = 200,
    gerar_parents: bool = True,
    parent_max_chars: int = 3000,
    child_max_chars: int = 500,
) -> tuple[list[dict], dict[str, str]]:
    """Divide sections into chunks for indexing. Supports parent-child mode."""
    chunks = []
    parent_child_map: dict[str, str] = {}
    slug = re.sub(r'[^a-z0-9]', '_', fonte.lower())
    hash_suffix = hashlib.md5(fonte.encode()).hexdigest()[:6]
    prefixo = f"{slug[:24]}_{hash_suffix}"
    ids_vistos: dict[str, int] = {}

    def _id_unico(base_id: str) -> str:
        if base_id not in ids_vistos:
            ids_vistos[base_id] = 0
            return base_id
        ids_vistos[base_id] += 1
        return f"{base_id}_dup{ids_vistos[base_id]}"

    for secao in secoes:
        texto = secao["texto"]
        titulo_completo = f"{secao['numero']}. {secao['titulo']}"

        base_chunk = {
            "secao": secao["numero"],
            "titulo": secao["titulo"],
            "pagina": secao["pagina_inicio"],
            "fonte": fonte,
            "ano": ano,
            "tipo": tipo,
        }

        if not gerar_parents:
            if len(texto) <= max_chars:
                chunk_id = _id_unico(f"{prefixo}_secao_{secao['numero']}")
                chunks.append({
                    **base_chunk,
                    "id": chunk_id,
                    "texto": texto,
                    "contexto": f"[{fonte} - {titulo_completo} - Página {secao['pagina_inicio']}]\n\n{texto}",
                    "is_parent": False,
                })
            else:
                partes = _dividir_com_overlap(texto, max_chars, overlap)
                for idx, parte in enumerate(partes):
                    suffix = f" (parte {idx + 1})" if len(partes) > 1 else ""
                    base = (
                        f"{prefixo}_secao_{secao['numero']}_parte{idx}"
                        if idx > 0
                        else f"{prefixo}_secao_{secao['numero']}"
                    )
                    chunk_id = _id_unico(base)
                    chunks.append({
                        **base_chunk,
                        "id": chunk_id,
                        "texto": parte,
                        "contexto": f"[{fonte} - {titulo_completo}{suffix} - Página {secao['pagina_inicio']}]\n\n{parte}",
                        "is_parent": False,
                    })
        else:
            contextual_prefix = (
                f"[{fonte} | Seção {titulo_completo} | "
                f"Página {secao['pagina_inicio']} | Tipo: {tipo}]"
            )

            parent_partes = _dividir_com_overlap(texto, parent_max_chars, overlap)

            for p_idx, parent_texto in enumerate(parent_partes):
                parent_id = _id_unico(f"{prefixo}_secao_{secao['numero']}_parent{p_idx}")
                chunks.append({
                    **base_chunk,
                    "id": parent_id,
                    "texto": parent_texto,
                    "contexto": f"{contextual_prefix}\n\n{parent_texto}",
                    "is_parent": True,
                })

                child_partes = _dividir_com_overlap(parent_texto, child_max_chars, overlap)
                for c_idx, child_texto in enumerate(child_partes):
                    child_id = _id_unico(
                        f"{prefixo}_secao_{secao['numero']}_p{p_idx}_c{c_idx}"
                    )

                    parent_snippet = parent_texto[:200].rstrip()
                    if len(parent_texto) > 200:
                        parent_snippet += "..."
                    child_contexto = (
                        f"{contextual_prefix}\n\n"
                        f"Contexto da seção: {parent_snippet}\n\n"
                        f"{child_texto}"
                    )

                    chunks.append({
                        **base_chunk,
                        "id": child_id,
                        "texto": child_texto,
                        "contexto": child_contexto,
                        "is_parent": False,
                        "parent_id": parent_id,
                    })
                    parent_child_map[child_id] = parent_id

    return chunks, parent_child_map


def extrair_generico(
    paginas: list[dict],
    nome_fonte: str,
    max_chars: int = 1500,
    ano: str = "",
    tipo: str = "portaria",
    overlap: int = 200,
    gerar_parents: bool = True,
    parent_max_chars: int = 3000,
    child_max_chars: int = 500,
) -> tuple[list[dict], dict[str, str]]:
    """Generic extraction for PDFs without sections. Supports parent-child."""
    slug = re.sub(r'[^a-z0-9]', '_', nome_fonte.lower())
    hash_suffix = hashlib.md5(nome_fonte.encode()).hexdigest()[:6]
    prefixo = f"{slug[:24]}_{hash_suffix}"

    buffer_texto = ""
    buffer_pagina = 1
    blocos = []

    for pagina_info in paginas:
        pagina = pagina_info["pagina"]
        texto = pagina_info["texto"].strip()
        if not texto or texto.count("...") > 5:
            continue

        paragrafos = texto.split("\n\n")
        for paragrafo in paragrafos:
            paragrafo = paragrafo.strip()
            if not paragrafo or len(paragrafo) < 20:
                continue

            if len(buffer_texto) + len(paragrafo) > parent_max_chars and buffer_texto:
                blocos.append({"pagina": buffer_pagina, "texto": buffer_texto.strip()})
                buffer_texto = paragrafo + "\n\n"
                buffer_pagina = pagina
            else:
                if not buffer_texto:
                    buffer_pagina = pagina
                buffer_texto += paragrafo + "\n\n"

    if buffer_texto.strip():
        blocos.append({"pagina": buffer_pagina, "texto": buffer_texto.strip()})

    chunks = []
    parent_child_map: dict[str, str] = {}
    chunk_idx = 0

    for bloco in blocos:
        pagina = bloco["pagina"]
        texto = bloco["texto"]

        base_chunk = {
            "secao": str(pagina),
            "titulo": f"Página {pagina}",
            "pagina": pagina,
            "fonte": nome_fonte,
            "ano": ano,
            "tipo": tipo,
        }

        contextual_prefix = f"[{nome_fonte} | Página {pagina} | Tipo: {tipo}]"

        if not gerar_parents:
            partes = _dividir_com_overlap(texto, max_chars, overlap)
            for parte in partes:
                chunk_id = f"{prefixo}_p{pagina}_c{chunk_idx}"
                chunks.append({
                    **base_chunk,
                    "id": chunk_id,
                    "texto": parte,
                    "contexto": f"[{nome_fonte} - Página {pagina}]\n\n{parte}",
                    "is_parent": False,
                })
                chunk_idx += 1
        else:
            parent_id = f"{prefixo}_p{pagina}_parent{chunk_idx}"
            chunks.append({
                **base_chunk,
                "id": parent_id,
                "texto": texto,
                "contexto": f"{contextual_prefix}\n\n{texto}",
                "is_parent": True,
            })

            child_partes = _dividir_com_overlap(texto, child_max_chars, overlap)
            for c_idx, child_texto in enumerate(child_partes):
                child_id = f"{prefixo}_p{pagina}_c{chunk_idx}_{c_idx}"

                parent_snippet = texto[:200].rstrip()
                if len(texto) > 200:
                    parent_snippet += "..."
                child_contexto = (
                    f"{contextual_prefix}\n\n"
                    f"Contexto: {parent_snippet}\n\n"
                    f"{child_texto}"
                )

                chunks.append({
                    **base_chunk,
                    "id": child_id,
                    "texto": child_texto,
                    "contexto": child_contexto,
                    "is_parent": False,
                    "parent_id": parent_id,
                })
                parent_child_map[child_id] = parent_id

            chunk_idx += 1

    return chunks, parent_child_map


def eh_manual_sih(paginas: list[dict]) -> bool:
    """Detect if a PDF is the Manual SIH/SUS by content."""
    texto_inicio = " ".join(p["texto"] for p in paginas[:10]).upper()
    indicadores = [
        "SISTEMA DE INFORMAÇÃO HOSPITALAR",
        "MANUAL TÉCNICO OPERACIONAL",
        "SIH/SUS",
        "AIH",
    ]
    matches = sum(1 for ind in indicadores if ind in texto_inicio)
    return matches >= 2


def eh_anexo_sigtap(nome: str) -> bool:
    """Detect if the file is a SIGTAP annex."""
    nome_lower = nome.lower()
    indicadores = ["anexo", "relatorio_grupo", "relatorio_analitico"]
    return any(ind in nome_lower for ind in indicadores)


def extrair_ano_do_path(path: Any) -> str:
    """Extract year from paths like portaria2007/ -> '2007'."""
    from pathlib import Path

    path = Path(path)
    for parte in path.parts:
        match = re.search(r'(\d{4})', parte)
        if match:
            ano = match.group(1)
            if 2000 <= int(ano) <= 2030:
                return ano
    return ""


def nome_fonte_legivel(path: Any, ano: str = "") -> str:
    """Generate readable source name from file path."""
    from pathlib import Path

    path = Path(path)
    nome = path.stem
    nome = re.sub(r'[╓╟αΘσ]', '', nome)
    nome = nome.replace("_", " ").replace("-", " ").replace("  ", " ").strip()
    if len(nome) > 60:
        nome = nome[:60]
    if ano:
        nome = f"{nome} ({ano})"
    return nome
