"""
Extrai texto de PDFs, HTMLs, DOCs e ZIPs para indexacao RAG.

Suporta multiplos formatos:
  - PDF: Manual SIH/SUS (deteccao de secoes) ou generico (por pagina)
  - HTML/HTM: Portarias em HTML (encoding windows-1252/latin-1)
  - DOC: Documentos legados via libreoffice --headless
  - ZIP: Extrai e processa recursivamente

Uso:
  python extrair_manual.py                           # auto-detecta PDFs no projeto
  python extrair_manual.py manual.pdf                # um PDF
  python extrair_manual.py manual.pdf portaria.pdf   # multiplos PDFs
  python extrair_manual.py --adicionar novo.pdf      # adiciona sem apagar chunks existentes
  python extrair_manual.py --ragdata ragData/        # processa todo o diretorio ragData
"""

import json
import sys
from pathlib import Path

from manual_sih_rag.extraction.pdf_extractor import (  # noqa: F401
    EXTENSOES_SUPORTADAS,
    MAX_CHARS_HTML,
    MAX_PAGINAS_ANEXO,
    criar_chunks,
    detectar_secoes,
    eh_anexo_sigtap,
    eh_manual_sih,
    extrair_ano_do_path,
    extrair_generico,
    extrair_texto_paginas,
    nome_fonte_legivel,
)
from manual_sih_rag.extraction.format_handlers import (  # noqa: F401
    extrair_doc,
    extrair_html,
    processar_doc,
    processar_html,
    processar_zip,
)


def processar_pdf(
    pdf_path: str,
    ano: str = "",
    tipo: str = "",
) -> tuple[list[dict], list[dict]]:
    """Processa um PDF e retorna (secoes, chunks). Includes SIH naming logic."""
    path = Path(pdf_path)
    nome_fonte = nome_fonte_legivel(path, ano)

    is_anexo = eh_anexo_sigtap(path.name)
    if not tipo:
        tipo = "anexo_sigtap" if is_anexo else "manual"

    print(f"\nExtraindo texto de: {path.name}")
    max_pags = MAX_PAGINAS_ANEXO if is_anexo else 0
    if is_anexo:
        print(f"  Anexo SIGTAP detectado: limitando a {MAX_PAGINAS_ANEXO} paginas")

    paginas = extrair_texto_paginas(pdf_path, max_paginas=max_pags)
    print(f"  {len(paginas)} paginas com texto extraido")

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
        print(f"  {len(secoes)} secoes encontradas")
        if secoes:
            chunks, _pcmap = criar_chunks(secoes, fonte=nome_fonte, ano=ano, tipo=tipo)
        else:
            print(f"  Fallback: usando extracao generica")
            chunks, _pcmap = extrair_generico(paginas, nome_fonte, ano=ano, tipo=tipo)
    else:
        print(f"  Formato: PDF generico | Fonte: {nome_fonte}")
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
    """Dispatcher: processa um arquivo pela extensao."""
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
        print(f"  Formato nao suportado: {ext}")
        return [], []


def descobrir_arquivos(base_dir: Path) -> list[Path]:
    """Descobre recursivamente todos os arquivos processaveis em um diretorio."""
    arquivos = []
    for path in sorted(base_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in EXTENSOES_SUPORTADAS:
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

    if ragdata_flag:
        ragdata_dir = None
        for i, a in enumerate(sys.argv):
            if a == "--ragdata" and i + 1 < len(sys.argv):
                ragdata_dir = Path(sys.argv[i + 1])
                break

        if not ragdata_dir:
            ragdata_dir = Path(__file__).parent / "ragData"

        if not ragdata_dir.exists():
            print(f"Erro: diretorio '{ragdata_dir}' nao encontrado.")
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

        _salvar_resultados(output_dir, todos_secoes, todos_chunks, erros)
        return

    # Modo legacy: PDFs por argumento
    pdf_paths = []
    for a in args:
        p = Path(a)
        if p.exists() and p.suffix.lower() == ".pdf":
            pdf_paths.append(str(p.resolve()))
        else:
            print(f"Aviso: '{a}' nao e um PDF valido, ignorando.")

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
            print("  python extrair_manual.py --ragdata <diretorio>")
            print("")
            print("Ou coloque PDFs no diretorio do projeto para auto-deteccao.")
            sys.exit(1)

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

    for pdf_path in pdf_paths:
        secoes, chunks = processar_pdf(pdf_path)

        if chunks:
            fonte = chunks[0].get("fonte", "?")
            if adicionar and fonte in fontes_existentes:
                print(f"  Aviso: fonte '{fonte}' ja existe. Substituindo chunks dessa fonte.")
                todos_chunks = [c for c in todos_chunks if c.get("fonte", "Manual SIH/SUS") != fonte]
                todos_secoes = [s for s in todos_secoes if s.get("fonte", "Manual SIH/SUS") != fonte]

        todos_secoes.extend(secoes)
        todos_chunks.extend(chunks)

    _salvar_resultados(output_dir, todos_secoes, todos_chunks)


def _salvar_resultados(
    output_dir: Path,
    todos_secoes: list[dict],
    todos_chunks: list[dict],
    erros: list[dict] | None = None,
):
    """Salva secoes, chunks e parent-child map em disco."""
    with open(output_dir / "secoes.json", "w", encoding="utf-8") as f:
        json.dump(todos_secoes, f, ensure_ascii=False, indent=2)

    with open(output_dir / "chunks.json", "w", encoding="utf-8") as f:
        json.dump(todos_chunks, f, ensure_ascii=False, indent=2)

    parent_child_map = {}
    for c in todos_chunks:
        if "parent_id" in c:
            parent_child_map[c["id"]] = c["parent_id"]

    if parent_child_map:
        with open(output_dir / "parent_child_map.json", "w", encoding="utf-8") as f:
            json.dump(parent_child_map, f, ensure_ascii=False, indent=2)
        print(f"  Parent-child map: {len(parent_child_map)} mappings")

    fontes = {}
    tipos = {}
    for c in todos_chunks:
        fonte = c.get("fonte", "?")
        fontes[fonte] = fontes.get(fonte, 0) + 1
        tp = c.get("tipo", "?")
        tipos[tp] = tipos.get(tp, 0) + 1

    print(f"\n{'='*60}")
    print(f"Total: {len(todos_chunks)} chunks de {len(fontes)} fonte(s)")
    if tipos:
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
    print(f"\nProximo passo: python indexar_manual.py")


if __name__ == "__main__":
    main()
