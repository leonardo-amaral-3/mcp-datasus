"""Validates a critica showing code logic, manual sections, and interactive mode.

Extracted from root validar_critica.py — core functions only (no CLI main).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .paths import CRITICAS_DIR, CRITICAS_TS, PROJETO_DIR


def ler_definicao_critica(numero: int) -> dict | None:
    """Read critica definition from criticas.ts."""
    conteudo = CRITICAS_TS.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"CRITICA_{numero}:\s*\{{\s*"
        r"codigo:\s*'(\d+)'\s*,\s*"
        r"nome:\s*'([^']+)'\s*,\s*"
        r"campos:\s*\[([^\]]*)\]",
        re.MULTILINE,
    )
    match = pattern.search(conteudo)
    if not match:
        return None
    campos_raw = match.group(3)
    campos = [c.strip().strip("'\"") for c in campos_raw.split(",") if c.strip()]
    return {
        "numero": numero,
        "codigo": match.group(1),
        "nome": match.group(2),
        "campos": campos,
    }


def ler_codigo_critica(numero: int) -> str | None:
    """Read TypeScript source for a critica."""
    arquivo = CRITICAS_DIR / f"critica{numero}" / f"critica{numero}.ts"
    if not arquivo.exists():
        return None
    return arquivo.read_text(encoding="utf-8")


def extrair_logica_hasCritica(codigo: str) -> str:
    """Extract only the hasCritica function, removing debug lines."""
    linhas = codigo.split("\n")
    inicio = None
    for i, linha in enumerate(linhas):
        if "hasCritica" in linha and ("const" in linha or "async" in linha):
            inicio = i
            break

    if inicio is None:
        resultado = []
        for linha in linhas:
            stripped = linha.strip()
            if stripped.startswith("import ") or stripped.startswith("} from"):
                continue
            if stripped.startswith("if (isDebug)") or stripped.startswith("console.log"):
                continue
            if "DEBUG" in stripped and "const DEBUG" not in stripped:
                continue
            resultado.append(linha)
        return "\n".join(resultado).strip()

    nivel = 0
    resultado = []
    encontrou_primeira_chave = False

    for i in range(inicio, len(linhas)):
        linha = linhas[i]
        stripped = linha.strip()

        if stripped.startswith("if (isDebug)") or stripped.startswith("console.log"):
            continue
        if "DEBUG" in stripped and "const DEBUG" not in stripped:
            continue

        resultado.append(linha)

        for ch in linha:
            if ch == "{":
                nivel += 1
                encontrou_primeira_chave = True
            elif ch == "}":
                nivel -= 1

        if encontrou_primeira_chave and nivel <= 0:
            break

    return "\n".join(resultado)


def extrair_termos_busca(codigo: str, nome: str) -> list[str]:
    """Analyze code to generate manual search queries."""
    termos = []

    if "PROCEDIMENTOS_FISIOTERAPIA" in codigo:
        termos.append("fisioterapia atendimento fisioterapeutico quantidade maxima por dia internacao")
    if "calcularDiasInternacao" in codigo:
        termos.append("dias de internacao permanencia calculo por competencia")
    if "rlProcedimentoCid" in codigo:
        termos.append("compatibilidade CID diagnostico procedimento SIGTAP CID-10")
    if "rlProcedimentoSexo" in codigo or "sexoPaciente" in codigo.lower():
        termos.append("sexo paciente incompativel procedimento diagnostico")
    if "idadeMinima" in codigo or "idadeMaxima" in codigo or "calcularIdade" in codigo:
        termos.append("idade paciente minima maxima procedimento faixa etaria")
    if "permanencia" in codigo.lower() or "mediaPermanencia" in codigo.lower():
        termos.append("media permanencia dias SIGTAP liberacao critica")
    if "duplici" in codigo.lower():
        termos.append("duplicidade AIH mesmo paciente reinternacao 03 dias bloqueio")
    if "opm" in codigo.lower() or "OPM" in codigo:
        termos.append("OPM orteses proteses materiais especiais compatibilidade quantidade")
    if "cbo" in codigo.lower():
        termos.append("CBO classificacao brasileira ocupacoes medico profissional CNES")
    if "cnes" in codigo.lower():
        termos.append("CNES cadastro nacional estabelecimentos habilitacao")
    if "anestesia" in codigo.lower():
        termos.append("anestesia regional geral sedacao cirurgiao obstetrica")
    if "hemoterapia" in codigo.lower() or "transfus" in codigo.lower():
        termos.append("hemoterapia transfusao sangue agencia transfusional")
    if "leito" in codigo.lower():
        termos.append("especialidade leito UTI UCI CNES cadastro")
    if "acompanhante" in codigo.lower() or "diaria" in codigo.lower():
        termos.append("diaria acompanhante idoso gestante UTI")
    if "transplante" in codigo.lower():
        termos.append("transplante orgaos doacao retirada intercorrencia")
    if "politraumatizado" in codigo.lower() or "cirurgiaMultipla" in codigo.lower():
        termos.append("politraumatizado cirurgia multipla tratamento")
    if "motivoSaida" in codigo or "motivoApresentacao" in codigo.lower():
        termos.append("motivo apresentacao alta permanencia transferencia obito")
    if "quantidadeRealizada" in codigo or "quantidadeMaxima" in codigo.lower():
        termos.append("quantidade maxima procedimentos AIH limite SIGTAP")
    if "competencia" in codigo.lower():
        termos.append("competencia execucao processamento apresentacao AIH")

    termos.append(nome)
    return termos


def buscar_manual(
    queries: list[str], model: Any, collection: Any, n_por_query: int = 3
) -> list[dict]:
    """Search manual using multiple queries, deduplicating and ranking."""
    # Try hybrid search
    try:
        from manual_sih_rag.rag.hybrid_search import buscar_manual_hibrida, _bm25

        if _bm25 is not None:
            return buscar_manual_hibrida(queries, model, collection, n_por_query)
    except (ImportError, Exception):
        pass

    # Fallback: vector search
    todos: dict[str, dict] = {}

    for query in queries:
        embedding = model.encode([query], normalize_embeddings=True)
        resultado = collection.query(
            query_embeddings=[embedding[0].tolist()],
            n_results=n_por_query,
            include=["documents", "metadatas", "distances"],
        )
        for i in range(len(resultado["ids"][0])):
            rid = resultado["ids"][0][i]
            score = 1 - resultado["distances"][0][i]
            if rid not in todos or score > todos[rid]["relevancia"]:
                texto = resultado["documents"][0][i]
                if texto.startswith("[Manual"):
                    idx = texto.find("]\n\n")
                    if idx > 0:
                        texto = texto[idx + 3:]
                todos[rid] = {
                    "id": rid,
                    "secao": resultado["metadatas"][0][i]["secao"],
                    "titulo": resultado["metadatas"][0][i]["titulo"].split("\n")[0].strip(),
                    "pagina": resultado["metadatas"][0][i]["pagina"],
                    "texto": texto,
                    "relevancia": round(score, 3),
                    "query_origem": query[:60],
                }

    return sorted(todos.values(), key=lambda x: -x["relevancia"])


def listar_arquivos_critica(numero: int) -> list[str]:
    """List all files related to a critica."""
    pasta = CRITICAS_DIR / f"critica{numero}"
    arquivos = []
    if pasta.exists():
        for f in sorted(pasta.rglob("*.ts")):
            arquivos.append(str(f.relative_to(PROJETO_DIR)))
    tests_dir = PROJETO_DIR / "__tests__"
    if tests_dir.exists():
        for f in sorted(tests_dir.rglob(f"*critica{numero}*")):
            arquivos.append(str(f.relative_to(PROJETO_DIR)))
    return arquivos
