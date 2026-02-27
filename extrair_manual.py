"""
Extrai texto de PDFs, HTMLs, DOCs e ZIPs para indexação RAG.

Suporta múltiplos formatos:
  - PDF: Manual SIH/SUS (detecção de seções) ou genérico (por página)
  - HTML/HTM: Portarias em HTML (encoding windows-1252/latin-1)
  - DOC: Documentos legados via libreoffice --headless
  - ZIP: Extrai e processa recursivamente

Uso:
  python extrair_manual.py                           # auto-detecta PDFs no projeto
  python extrair_manual.py manual.pdf                # um PDF
  python extrair_manual.py manual.pdf portaria.pdf   # múltiplos PDFs
  python extrair_manual.py --adicionar novo.pdf      # adiciona sem apagar chunks existentes
  python extrair_manual.py --ragdata ragData/        # processa todo o diretório ragData
"""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf

EXTENSOES_SUPORTADAS = {".pdf", ".htm", ".html", ".doc", ".zip"}
MAX_PAGINAS_ANEXO = 10
MAX_CHARS_HTML = 50000


def extrair_texto_paginas(pdf_path: str, max_paginas: int = 0) -> list[dict]:
    """Extrai texto de cada página do PDF. max_paginas=0 significa sem limite."""
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
    """
    Detecta seções do manual baseado nos padrões de título.
    Padrões: "1. APRESENTAÇÃO", "4.3 LAUDO PARA...", "62.1 CID X PROCEDIMENTO", etc.
    Também lida com títulos em linhas separadas (ex: "22.\nFISIOTERAPIA").
    """
    padrao_secao = re.compile(
        r'^(\d{1,2}(?:\.\d{1,2})?(?:\.\d{1,2})?)\s+'
        r'([A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s\-/,\(\)\.]+)',
        re.MULTILINE,
    )

    secoes = []
    secao_atual = None
    texto_acumulado = []

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

            numero_match = re.match(r'^(\d{1,2}(?:\.\d{1,2})?(?:\.\d{1,2})?)\s*\.?\s*$', stripped)
            if numero_match and i + 1 < len(linhas_filtradas):
                proxima = linhas_filtradas[i + 1].strip()
                if proxima and re.match(r'^[A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ][A-ZÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ\s\-/,\(\)\.]+$', proxima):
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
            for i, match in enumerate(matches):
                if secao_atual:
                    if i == 0:
                        texto_antes = texto_limpo[: match.start()].strip()
                        if texto_antes:
                            texto_acumulado.append(texto_antes)

                    secao_atual["texto"] = "\n".join(texto_acumulado).strip()
                    if secao_atual["texto"]:
                        secoes.append(secao_atual)
                    texto_acumulado = []

                elif i == 0:
                    texto_antes = texto_limpo[: match.start()].strip()
                    if texto_antes and pagina > 8:
                        secoes.append(
                            {
                                "numero": "0",
                                "titulo": "PREÂMBULO",
                                "pagina_inicio": pagina,
                                "texto": texto_antes,
                            }
                        )

                inicio_texto = match.end()
                if i + 1 < len(matches):
                    fim_texto = matches[i + 1].start()
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


def _dividir_com_overlap(
    texto: str,
    max_chars: int,
    overlap: int = 200,
) -> list[str]:
    """Split text into chunks with overlap between consecutive pieces."""
    if len(texto) <= max_chars:
        return [texto]

    paragrafos = texto.split("\n\n")
    chunks = []
    current_parts = []
    current_len = 0

    for para in paragrafos:
        if current_len + len(para) > max_chars and current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(chunk_text)

            # Keep last ~overlap chars worth of paragraphs
            overlap_parts = []
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
    """
    Divide seções em chunks para indexação.

    Quando gerar_parents=True:
      - Parent chunks (~3000 chars) para contexto LLM
      - Child chunks (~500 chars com overlap) para precisão de busca
      - Retorna mapa child_id → parent_id

    Quando gerar_parents=False:
      - Comportamento original: chunks de max_chars
    """
    chunks = []
    parent_child_map = {}
    slug = re.sub(r'[^a-z0-9]', '_', fonte.lower())
    hash_suffix = hashlib.md5(fonte.encode()).hexdigest()[:6]
    prefixo = f"{slug[:24]}_{hash_suffix}"
    ids_vistos = {}

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
            # === Modo legado (compatível com comportamento anterior) ===
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
                    base = f"{prefixo}_secao_{secao['numero']}_parte{idx}" if idx > 0 else f"{prefixo}_secao_{secao['numero']}"
                    chunk_id = _id_unico(base)
                    chunks.append({
                        **base_chunk,
                        "id": chunk_id,
                        "texto": parte,
                        "contexto": f"[{fonte} - {titulo_completo}{suffix} - Página {secao['pagina_inicio']}]\n\n{parte}",
                        "is_parent": False,
                    })
        else:
            # === Modo parent-child com contextual embeddings ===
            contextual_prefix = (
                f"[{fonte} | Seção {titulo_completo} | "
                f"Página {secao['pagina_inicio']} | Tipo: {tipo}]"
            )

            # Gerar parent chunks
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

                # Gerar child chunks de cada parent
                child_partes = _dividir_com_overlap(parent_texto, child_max_chars, overlap)

                for c_idx, child_texto in enumerate(child_partes):
                    child_id = _id_unico(
                        f"{prefixo}_secao_{secao['numero']}_p{p_idx}_c{c_idx}"
                    )

                    # Contextual embedding: prefix + snippet do parent + child text
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
    """
    Extração genérica para PDFs/documentos sem seções. Suporta parent-child.
    Retorna (chunks, parent_child_map).
    """
    slug = re.sub(r'[^a-z0-9]', '_', nome_fonte.lower())
    hash_suffix = hashlib.md5(nome_fonte.encode()).hexdigest()[:6]
    prefixo = f"{slug[:24]}_{hash_suffix}"

    # Primeiro: acumular texto por pagina em blocos grandes
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

    # Agora gerar chunks parent-child de cada bloco
    chunks = []
    parent_child_map = {}
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
            # Modo legado
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
            # Parent chunk
            parent_id = f"{prefixo}_p{pagina}_parent{chunk_idx}"
            chunks.append({
                **base_chunk,
                "id": parent_id,
                "texto": texto,
                "contexto": f"{contextual_prefix}\n\n{texto}",
                "is_parent": True,
            })

            # Child chunks
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
    """Detecta se o PDF é o Manual SIH/SUS pelo conteúdo das primeiras páginas."""
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
    """Detecta se o arquivo é um anexo SIGTAP (tabela de procedimentos)."""
    nome_lower = nome.lower()
    indicadores = ["anexo", "relatorio_grupo", "relatorio_analitico"]
    return any(ind in nome_lower for ind in indicadores)


def extrair_ano_do_path(path: Path) -> str:
    """Extrai ano de caminhos como portaria2007/ -> '2007'."""
    for parte in path.parts:
        match = re.search(r'(\d{4})', parte)
        if match:
            ano = match.group(1)
            if 2000 <= int(ano) <= 2030:
                return ano
    return ""


def nome_fonte_legivel(path: Path, ano: str = "") -> str:
    """Gera nome de fonte legível a partir do caminho do arquivo."""
    nome = path.stem
    # Limpar caracteres especiais de encoding corrompido
    nome = re.sub(r'[╓╟αΘσ]', '', nome)
    # Substituir separadores por espaço
    nome = nome.replace("_", " ").replace("-", " ").replace("  ", " ").strip()
    # Limitar tamanho
    if len(nome) > 60:
        nome = nome[:60]
    if ano:
        nome = f"{nome} ({ano})"
    return nome


# ---- Extratores por formato ----

def extrair_html(path: Path) -> list[dict]:
    """Extrai texto de arquivo HTML com cascade de encodings."""
    from bs4 import BeautifulSoup

    conteudo = None
    for enc in ("windows-1252", "latin-1", "utf-8", "iso-8859-1"):
        try:
            conteudo = path.read_bytes().decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if not conteudo:
        print(f"  Aviso: não foi possível decodificar {path.name}")
        return []

    soup = BeautifulSoup(conteudo, "html.parser")

    # Remover scripts e styles
    for tag in soup(["script", "style"]):
        tag.decompose()

    texto = soup.get_text(separator="\n")
    # Limpar linhas vazias excessivas
    texto = re.sub(r'\n{3,}', '\n\n', texto).strip()

    # Truncar se muito grande (tabelas HTML enormes)
    if len(texto) > MAX_CHARS_HTML:
        texto = texto[:MAX_CHARS_HTML] + "\n\n[... conteúdo truncado ...]"

    if len(texto) < 50:
        return []

    return [{"pagina": 1, "texto": texto}]


def extrair_doc(path: Path) -> list[dict]:
    """Extrai texto de arquivo DOC via libreoffice."""
    if not shutil.which("libreoffice"):
        print(f"  Aviso: libreoffice não encontrado, pulando {path.name}")
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

        # Encontrar arquivo .txt gerado
        txts = list(Path(tmpdir).glob("*.txt"))
        if not txts:
            print(f"  Aviso: libreoffice não gerou txt para {path.name}")
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


def processar_zip(path: Path, ano: str = "", tipo: str = "portaria") -> tuple[list[dict], list[dict]]:
    """Extrai arquivos de um ZIP e processa recursivamente dentro do contexto temporário."""
    todas_secoes, todos_chunks = [], []
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
                    secoes, chunks = processar_pdf(str(arq), ano=ano, tipo=tipo)
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


# ---- Processadores ----

def processar_pdf(
    pdf_path: str,
    ano: str = "",
    tipo: str = "",
) -> tuple[list[dict], list[dict]]:
    """Processa um PDF e retorna (secoes, chunks)."""
    path = Path(pdf_path)
    nome_fonte = nome_fonte_legivel(path, ano)

    is_anexo = eh_anexo_sigtap(path.name)
    if not tipo:
        tipo = "anexo_sigtap" if is_anexo else "manual"

    print(f"\nExtraindo texto de: {path.name}")
    max_pags = MAX_PAGINAS_ANEXO if is_anexo else 0
    if is_anexo:
        print(f"  Anexo SIGTAP detectado: limitando a {MAX_PAGINAS_ANEXO} páginas")

    paginas = extrair_texto_paginas(pdf_path, max_paginas=max_pags)
    print(f"  {len(paginas)} páginas com texto extraído")

    if eh_manual_sih(paginas):
        if "2017" in str(path) or "2017" in nome_fonte:
            nome_fonte = "Manual SIH/SUS 2017"
        elif "sia" in nome_fonte.lower() or "SIA" in str(path):
            nome_fonte = "Manual SIA/SUS"
        elif "manual_tecnico_sistema" in str(path).lower() or "manual sih" in nome_fonte.lower():
            nome_fonte = "Manual SIH/SUS 2012"
        tipo = "manual"
        print(f"  Formato: Manual SIH/SUS | Fonte: {nome_fonte}")
        secoes = detectar_secoes(paginas)
        print(f"  {len(secoes)} seções encontradas")
        if secoes:
            chunks, _pcmap = criar_chunks(secoes, fonte=nome_fonte, ano=ano, tipo=tipo)
        else:
            # Fallback: detectou SIH mas sem seções -> usar genérico
            print(f"  Fallback: usando extração genérica")
            chunks, _pcmap = extrair_generico(paginas, nome_fonte, ano=ano, tipo=tipo)
    else:
        print(f"  Formato: PDF genérico | Fonte: {nome_fonte}")
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


def processar_html(
    html_path: Path,
    ano: str = "",
    tipo: str = "portaria",
) -> tuple[list[dict], list[dict]]:
    """Processa um arquivo HTML e retorna (secoes, chunks)."""
    nome_fonte = nome_fonte_legivel(html_path, ano)
    print(f"\nExtraindo HTML: {html_path.name}")

    paginas = extrair_html(html_path)
    if not paginas:
        print(f"  Sem conteúdo extraível")
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
    doc_path: Path,
    ano: str = "",
    tipo: str = "portaria",
) -> tuple[list[dict], list[dict]]:
    """Processa um arquivo DOC e retorna (secoes, chunks)."""
    nome_fonte = nome_fonte_legivel(doc_path, ano)
    print(f"\nExtraindo DOC: {doc_path.name}")

    paginas = extrair_doc(doc_path)
    if not paginas:
        print(f"  Sem conteúdo extraível")
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


def processar_arquivo(path: Path, ano: str = "", tipo: str = "") -> tuple[list[dict], list[dict]]:
    """Dispatcher: processa um arquivo pela extensão."""
    ext = path.suffix.lower()

    if not ano:
        ano = extrair_ano_do_path(path)
    if not tipo:
        tipo = "portaria" if "portaria" in str(path).lower() else "manual"

    if ext == ".pdf":
        return processar_pdf(str(path), ano=ano, tipo=tipo)
    elif ext in (".htm", ".html"):
        return processar_html(path, ano=ano, tipo=tipo)
    elif ext == ".doc":
        return processar_doc(path, ano=ano, tipo=tipo)
    elif ext == ".zip":
        print(f"\nExtraindo ZIP: {path.name}")
        return processar_zip(path, ano=ano, tipo=tipo)
    else:
        print(f"  Formato não suportado: {ext}")
        return [], []


def descobrir_arquivos(base_dir: Path) -> list[Path]:
    """Descobre recursivamente todos os arquivos processáveis em um diretório."""
    arquivos = []
    for path in sorted(base_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in EXTENSOES_SUPORTADAS:
            # Ignorar arquivos ocultos e diretórios de metadata
            if any(part.startswith(".") for part in path.relative_to(base_dir).parts):
                continue
            arquivos.append(path)
    return arquivos


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    adicionar = "--adicionar" in sys.argv
    ragdata_flag = "--ragdata" in sys.argv

    output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(exist_ok=True)

    # Modo --ragdata: processar diretório inteiro
    if ragdata_flag:
        ragdata_dir = None
        for i, a in enumerate(sys.argv):
            if a == "--ragdata" and i + 1 < len(sys.argv):
                ragdata_dir = Path(sys.argv[i + 1])
                break

        if not ragdata_dir:
            # Default: ragData/ relativo ao script
            ragdata_dir = Path(__file__).parent / "ragData"

        if not ragdata_dir.exists():
            print(f"Erro: diretório '{ragdata_dir}' não encontrado.")
            sys.exit(1)

        arquivos = descobrir_arquivos(ragdata_dir)
        print(f"Encontrados {len(arquivos)} arquivos em {ragdata_dir}")
        print(f"  PDF: {sum(1 for a in arquivos if a.suffix.lower() == '.pdf')}")
        print(f"  HTML/HTM: {sum(1 for a in arquivos if a.suffix.lower() in ('.htm', '.html'))}")
        print(f"  DOC: {sum(1 for a in arquivos if a.suffix.lower() == '.doc')}")
        print(f"  ZIP: {sum(1 for a in arquivos if a.suffix.lower() == '.zip')}")

        todos_secoes = []
        todos_chunks = []
        erros = []

        for arq in arquivos:
            try:
                secoes, chunks = processar_arquivo(arq)
                todos_secoes.extend(secoes)
                todos_chunks.extend(chunks)
            except Exception as e:
                print(f"  ERRO em {arq.name}: {e}")
                erros.append({"arquivo": str(arq), "erro": str(e)})

        # Salvar
        with open(output_dir / "secoes.json", "w", encoding="utf-8") as f:
            json.dump(todos_secoes, f, ensure_ascii=False, indent=2)

        with open(output_dir / "chunks.json", "w", encoding="utf-8") as f:
            json.dump(todos_chunks, f, ensure_ascii=False, indent=2)

        # Salvar mapa parent-child
        parent_child_map = {}
        for c in todos_chunks:
            if "parent_id" in c:
                parent_child_map[c["id"]] = c["parent_id"]

        if parent_child_map:
            with open(output_dir / "parent_child_map.json", "w", encoding="utf-8") as f:
                json.dump(parent_child_map, f, ensure_ascii=False, indent=2)
            print(f"  Parent-child map: {len(parent_child_map)} mappings")

        # Resumo
        fontes = {}
        tipos = {}
        for c in todos_chunks:
            fonte = c.get("fonte", "?")
            fontes[fonte] = fontes.get(fonte, 0) + 1
            tp = c.get("tipo", "?")
            tipos[tp] = tipos.get(tp, 0) + 1

        print(f"\n{'='*60}")
        print(f"Total: {len(todos_chunks)} chunks de {len(fontes)} fonte(s)")
        print(f"\nPor tipo:")
        for tp, qtd in sorted(tipos.items()):
            print(f"  {tp}: {qtd} chunks")
        print(f"\nPor fonte:")
        for fonte, qtd in sorted(fontes.items()):
            print(f"  {fonte}: {qtd} chunks")
        if erros:
            print(f"\n{len(erros)} arquivo(s) com erro:")
            for e in erros:
                print(f"  {Path(e['arquivo']).name}: {e['erro']}")
        print(f"\nArquivos salvos em: {output_dir}")
        print(f"\nPróximo passo: python indexar_manual.py")
        return

    # Modo legacy: PDFs por argumento
    pdf_paths = []
    for a in args:
        p = Path(a)
        if p.exists() and p.suffix.lower() == ".pdf":
            pdf_paths.append(str(p.resolve()))
        else:
            print(f"Aviso: '{a}' não é um PDF válido, ignorando.")

    if not pdf_paths:
        projeto_dir = Path(__file__).parent.parent.parent
        candidatos = sorted(projeto_dir.glob("*.pdf"))
        if candidatos:
            pdf_paths = [str(p) for p in candidatos]
            print(f"Auto-detectados {len(pdf_paths)} PDFs em {projeto_dir}:")
            for p in pdf_paths:
                print(f"  - {Path(p).name}")
        else:
            print("Uso:")
            print("  python extrair_manual.py <pdf1> [pdf2] [pdf3] ...")
            print("  python extrair_manual.py --adicionar <novo.pdf>")
            print("  python extrair_manual.py --ragdata <diretório>")
            print("")
            print("Ou coloque PDFs no diretório do projeto para auto-detecção.")
            sys.exit(1)

    # Carregar chunks existentes se modo --adicionar
    todos_secoes = []
    todos_chunks = []

    if adicionar:
        chunks_path = output_dir / "chunks.json"
        secoes_path = output_dir / "secoes.json"
        if chunks_path.exists():
            with open(chunks_path, encoding="utf-8") as f:
                todos_chunks = json.load(f)
            print(f"Modo --adicionar: {len(todos_chunks)} chunks existentes mantidos")
        if secoes_path.exists():
            with open(secoes_path, encoding="utf-8") as f:
                todos_secoes = json.load(f)

        fontes_existentes = {c.get("fonte", "Manual SIH/SUS") for c in todos_chunks}
    else:
        fontes_existentes = set()

    # Processar cada PDF
    for pdf_path in pdf_paths:
        secoes, chunks = processar_pdf(pdf_path)

        if chunks:
            fonte = chunks[0].get("fonte", "?")
            if adicionar and fonte in fontes_existentes:
                print(f"  Aviso: fonte '{fonte}' já existe. Substituindo chunks dessa fonte.")
                todos_chunks = [c for c in todos_chunks if c.get("fonte", "Manual SIH/SUS") != fonte]
                todos_secoes = [s for s in todos_secoes if s.get("fonte", "Manual SIH/SUS") != fonte]

        todos_secoes.extend(secoes)
        todos_chunks.extend(chunks)

    # Salvar resultado
    with open(output_dir / "secoes.json", "w", encoding="utf-8") as f:
        json.dump(todos_secoes, f, ensure_ascii=False, indent=2)

    with open(output_dir / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(todos_chunks, f, ensure_ascii=False, indent=2)

    # Salvar mapa parent-child
    parent_child_map = {}
    for c in todos_chunks:
        if "parent_id" in c:
            parent_child_map[c["id"]] = c["parent_id"]

    if parent_child_map:
        with open(output_dir / "parent_child_map.json", "w", encoding="utf-8") as f:
            json.dump(parent_child_map, f, ensure_ascii=False, indent=2)
        print(f"  Parent-child map: {len(parent_child_map)} mappings")

    # Resumo
    fontes = {}
    for c in todos_chunks:
        fonte = c.get("fonte", "?")
        fontes[fonte] = fontes.get(fonte, 0) + 1

    print(f"\n{'='*60}")
    print(f"Total: {len(todos_chunks)} chunks de {len(fontes)} fonte(s)")
    for fonte, qtd in sorted(fontes.items()):
        print(f"  {fonte}: {qtd} chunks")
    print(f"\nArquivos salvos em: {output_dir}")
    print(f"\nPróximo passo: python indexar_manual.py")


if __name__ == "__main__":
    main()
