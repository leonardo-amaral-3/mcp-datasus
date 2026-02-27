"""Format-specific extraction handlers: HTML, DOC, ZIP.

Extracted from root extrair_manual.py.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .pdf_extractor import (
    MAX_CHARS_HTML,
    EXTENSOES_SUPORTADAS,
    extrair_ano_do_path,
    extrair_generico,
    nome_fonte_legivel,
)


def extrair_html(path: Path) -> list[dict]:
    """Extract text from HTML file with encoding cascade."""
    from bs4 import BeautifulSoup

    conteudo = None
    for enc in ("windows-1252", "latin-1", "utf-8", "iso-8859-1"):
        try:
            conteudo = path.read_bytes().decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if not conteudo:
        print(f"  Aviso: nao foi possivel decodificar {path.name}")
        return []

    soup = BeautifulSoup(conteudo, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    texto = soup.get_text(separator="\n")
    texto = re.sub(r'\n{3,}', '\n\n', texto).strip()

    if len(texto) > MAX_CHARS_HTML:
        texto = texto[:MAX_CHARS_HTML] + "\n\n[... conteudo truncado ...]"

    if len(texto) < 50:
        return []

    return [{"pagina": 1, "texto": texto}]


def extrair_doc(path: Path) -> list[dict]:
    """Extract text from DOC file via libreoffice."""
    if not shutil.which("libreoffice"):
        print(f"  Aviso: libreoffice nao encontrado, pulando {path.name}")
        return []

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run(
                ["libreoffice", "--headless", "--convert-to", "txt", "--outdir", tmpdir, str(path)],
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"  Aviso: erro ao converter {path.name}: {e}")
            return []

        txts = list(Path(tmpdir).glob("*.txt"))
        if not txts:
            print(f"  Aviso: libreoffice nao gerou txt para {path.name}")
            return []

        texto = None
        for enc in ("utf-8", "latin-1", "windows-1252"):
            try:
                texto = txts[0].read_bytes().decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if not texto or len(texto.strip()) < 50:
            return []

        return [{"pagina": 1, "texto": texto.strip()}]


def processar_html(
    html_path: Path, ano: str = "", tipo: str = "portaria",
) -> tuple[list[dict], list[dict]]:
    """Process an HTML file and return (secoes, chunks)."""
    nome_fonte = nome_fonte_legivel(html_path, ano)
    print(f"\nExtraindo HTML: {html_path.name}")

    paginas = extrair_html(html_path)
    if not paginas:
        print(f"  Sem conteudo extraivel")
        return [], []

    chunks, _pcmap = extrair_generico(paginas, nome_fonte, ano=ano, tipo=tipo)
    secoes = [
        {
            "numero": str(c["pagina"]),
            "titulo": c["titulo"],
            "pagina_inicio": c["pagina"],
            "texto": c["texto"],
            "fonte": nome_fonte,
        }
        for c in chunks
    ]
    print(f"  {len(chunks)} chunks gerados")
    return secoes, chunks


def processar_doc(
    doc_path: Path, ano: str = "", tipo: str = "portaria",
) -> tuple[list[dict], list[dict]]:
    """Process a DOC file and return (secoes, chunks)."""
    nome_fonte = nome_fonte_legivel(doc_path, ano)
    print(f"\nExtraindo DOC: {doc_path.name}")

    paginas = extrair_doc(doc_path)
    if not paginas:
        print(f"  Sem conteudo extraivel")
        return [], []

    chunks, _pcmap = extrair_generico(paginas, nome_fonte, ano=ano, tipo=tipo)
    secoes = [
        {
            "numero": str(c["pagina"]),
            "titulo": c["titulo"],
            "pagina_inicio": c["pagina"],
            "texto": c["texto"],
            "fonte": nome_fonte,
        }
        for c in chunks
    ]
    print(f"  {len(chunks)} chunks gerados")
    return secoes, chunks


def processar_zip(
    path: Path, ano: str = "", tipo: str = "portaria",
) -> tuple[list[dict], list[dict]]:
    """Extract files from a ZIP and process recursively."""
    from .pdf_extractor import (
        MAX_PAGINAS_ANEXO,
        detectar_secoes,
        eh_anexo_sigtap,
        eh_manual_sih,
        extrair_texto_paginas,
        criar_chunks,
    )

    todas_secoes: list[dict] = []
    todos_chunks: list[dict] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(tmpdir)
        except (zipfile.BadZipFile, OSError) as e:
            print(f"  Aviso: erro ao extrair {path.name}: {e}")
            return [], []

        arquivos = []
        for arquivo in sorted(Path(tmpdir).rglob("*")):
            if arquivo.is_file() and arquivo.suffix.lower() in EXTENSOES_SUPORTADAS - {".zip"}:
                arquivos.append(arquivo)

        print(f"  {len(arquivos)} arquivos encontrados dentro do ZIP")
        for arq in arquivos:
            ext = arq.suffix.lower()
            try:
                if ext == ".pdf":
                    secoes, chunks = _processar_pdf_interno(arq, ano=ano, tipo=tipo)
                elif ext in (".htm", ".html"):
                    secoes, chunks = processar_html(arq, ano=ano, tipo=tipo)
                elif ext == ".doc":
                    secoes, chunks = processar_doc(arq, ano=ano, tipo=tipo)
                else:
                    continue
                todas_secoes.extend(secoes)
                todos_chunks.extend(chunks)
            except Exception as e:
                print(f"    Erro em {arq.name}: {e}")

    return todas_secoes, todos_chunks


def _processar_pdf_interno(
    path: Path, ano: str = "", tipo: str = "",
) -> tuple[list[dict], list[dict]]:
    """Process a PDF file (internal helper to avoid circular import)."""
    from .pdf_extractor import (
        MAX_PAGINAS_ANEXO,
        criar_chunks,
        detectar_secoes,
        eh_anexo_sigtap,
        eh_manual_sih,
        extrair_generico,
        extrair_texto_paginas,
        nome_fonte_legivel,
    )

    nome_fonte = nome_fonte_legivel(path, ano)
    is_anexo = eh_anexo_sigtap(path.name)
    if not tipo:
        tipo = "anexo_sigtap" if is_anexo else "manual"

    print(f"\nExtraindo texto de: {path.name}")
    max_pags = MAX_PAGINAS_ANEXO if is_anexo else 0

    paginas = extrair_texto_paginas(str(path), max_paginas=max_pags)
    print(f"  {len(paginas)} paginas com texto extraido")

    if eh_manual_sih(paginas):
        tipo = "manual"
        secoes = detectar_secoes(paginas)
        if secoes:
            chunks, _ = criar_chunks(secoes, fonte=nome_fonte, ano=ano, tipo=tipo)
        else:
            chunks, _ = extrair_generico(paginas, nome_fonte, ano=ano, tipo=tipo)
    else:
        chunks, _ = extrair_generico(paginas, nome_fonte, ano=ano, tipo=tipo)
        secoes = [
            {
                "numero": str(c["pagina"]),
                "titulo": c["titulo"],
                "pagina_inicio": c["pagina"],
                "texto": c["texto"],
                "fonte": nome_fonte,
            }
            for c in chunks
        ]

    print(f"  {len(chunks)} chunks gerados")
    return secoes, chunks
