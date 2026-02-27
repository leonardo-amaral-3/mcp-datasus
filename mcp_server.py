"""
MCP Server para o sistema RAG do Manual SIH/SUS.

Expõe as ferramentas de busca semântica, análise de críticas e consulta
ao manual como tools MCP para uso direto no Claude Code.

Registro local:
  claude mcp add manual-sih -- .venv/bin/python mcp_server.py

Registro global (qualquer repo):
  claude mcp add --scope user manual-sih -- manual-sih-mcp
"""

import json
import os
import sys
from pathlib import Path

_BASE = Path(__file__).parent
sys.path.insert(0, str(_BASE))
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from mcp.server.fastmcp import FastMCP

_MCP_HOST = os.getenv("MCP_HOST", "0.0.0.0")
_MCP_PORT = int(os.getenv("MCP_PORT", "8200"))

mcp = FastMCP(
    "manual-sih",
    host=_MCP_HOST,
    port=_MCP_PORT,
    instructions=(
        "Servidor RAG para consulta do Manual Técnico SIH/SUS, SIA/SUS e portarias. "
        "Permite busca semântica no manual, análise de críticas de validação, "
        "consulta de seções específicas e extração de dados de AIH. "
        "Também consulta SIGTAP (procedimentos SUS) e CNES (dados de estabelecimentos) via MinIO. "
        "SEMPRE use buscar_manual antes de responder perguntas sobre regras SIH/SUS. "
        "Use consultar_procedimento para validar códigos e valores de procedimentos. "
        "Use consultar_cnes para verificar leitos, serviços e habilitações de um estabelecimento. "
        "Cite seções e páginas no formato [Seção X.Y, p.N]. "
        "Use verificar_citacao para confirmar que uma seção existe antes de citá-la."
    ),
)

# ---------------------------------------------------------------------------
# Lazy-loaded globals
# ---------------------------------------------------------------------------
_model = None
_collection = None
_mapeamento = None
_sistema_carregado = False


def _carregar_sistema():
    global _model, _collection, _mapeamento, _sistema_carregado
    if _sistema_carregado:
        return

    from consulta_manual import carregar_sistema

    _model, _collection = carregar_sistema()

    mapeamento_path = _BASE / "data" / "mapeamento_criticas_manual.json"
    if mapeamento_path.exists():
        _mapeamento = json.loads(mapeamento_path.read_text(encoding="utf-8"))
    else:
        _mapeamento = []

    _sistema_carregado = True


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def buscar_manual(query: str, n_resultados: int = 5) -> str:
    """Busca semântica no Manual Técnico SIH/SUS e portarias relacionadas.

    Retorna trechos relevantes com seção, título, página e score de relevância.
    Use para qualquer pergunta sobre regras, procedimentos, campos da AIH, validações.

    Args:
        query: Texto de busca em português. Pode ser pergunta, termos-chave ou descrição.
        n_resultados: Quantidade de resultados (1-10). Padrão: 5.
    """
    _carregar_sistema()
    from consulta_manual import buscar

    n = min(max(n_resultados, 1), 10)
    resultados = buscar(query, _model, _collection, n_resultados=n)

    saida = []
    for r in resultados:
        texto = r["texto"]
        if len(texto) > 2000:
            texto = texto[:2000] + "\n[...truncado]"
        saida.append({
            "secao": r["metadata"]["secao"],
            "titulo": r["metadata"]["titulo"].split("\n")[0].strip(),
            "pagina": r["metadata"]["pagina"],
            "relevancia": f"{r['score']:.0%}",
            "texto": texto,
        })

    return json.dumps(saida, ensure_ascii=False, indent=2)


@mcp.tool()
def buscar_critica(numero: int) -> str:
    """Busca informações sobre uma crítica específica do SIH/SUS pelo número.

    Retorna definição (código, nome, campos) e seções do manual que a fundamentam.

    Args:
        numero: Número da crítica (ex: 7, 92, 129).
    """
    _carregar_sistema()

    if not _mapeamento:
        return json.dumps({"erro": "Mapeamento de críticas não carregado."}, ensure_ascii=False)

    entrada = next((m for m in _mapeamento if m["numero"] == numero), None)
    if not entrada:
        return json.dumps({"erro": f"Crítica {numero} não encontrada."}, ensure_ascii=False)

    resultado = {
        "numero": entrada["numero"],
        "codigo": entrada["codigo"],
        "nome": entrada["nome"],
        "secoes_manual": list(entrada.get("secoes_manual", [])),
    }

    try:
        from validar_critica import ler_definicao_critica

        defn = ler_definicao_critica(numero)
        if defn:
            resultado["campos"] = defn.get("campos", [])
    except Exception:
        pass

    for secao_info in resultado["secoes_manual"]:
        try:
            docs = _collection.get(
                where={"secao": secao_info["secao"]},
                include=["documents", "metadatas"],
            )
            if docs["documents"]:
                texto = docs["documents"][0]
                if len(texto) > 1500:
                    texto = texto[:1500] + "\n[...truncado]"
                secao_info["texto"] = texto
        except Exception:
            pass

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def listar_criticas(filtro: str = "") -> str:
    """Lista as críticas do SIH/SUS com seus números, códigos e nomes.

    Use quando o usuário perguntar quais críticas existem ou precisar encontrar uma por nome.

    Args:
        filtro: Filtro opcional por texto no nome. Ex: 'permanência', 'sexo', 'OPM'.
    """
    _carregar_sistema()

    filtro_lower = filtro.lower()
    criticas = [
        {"numero": m["numero"], "codigo": m["codigo"], "nome": m["nome"]}
        for m in (_mapeamento or [])
        if not filtro_lower or filtro_lower in m["nome"].lower()
    ]
    return json.dumps(criticas, ensure_ascii=False, indent=2)


@mcp.tool()
def buscar_por_secao(secao_numero: str) -> str:
    """Busca uma seção específica do manual pelo número.

    Retorna todos os trechos indexados daquela seção.
    Use quando já souber o número da seção (ex: '8.6', '4.5.1').

    Args:
        secao_numero: Número da seção do manual. Ex: '4.5', '8.6', '22'.
    """
    _carregar_sistema()

    docs = _collection.get(
        where={"secao": secao_numero},
        include=["documents", "metadatas"],
    )
    if not docs["ids"]:
        return json.dumps(
            {"erro": f"Seção '{secao_numero}' não encontrada."},
            ensure_ascii=False,
        )

    resultados = []
    for i in range(len(docs["ids"])):
        texto = docs["documents"][i]
        if len(texto) > 2000:
            texto = texto[:2000] + "\n[...truncado]"
        meta = docs["metadatas"][i]
        resultados.append({
            "titulo": meta.get("titulo", "").split("\n")[0].strip(),
            "pagina": meta.get("pagina"),
            "fonte": meta.get("fonte", ""),
            "texto": texto,
        })
    return json.dumps(resultados, ensure_ascii=False, indent=2)


@mcp.tool()
def verificar_citacao(secao_numero: str, verificar_texto: str = "") -> str:
    """Verifica se uma seção do manual existe no banco de dados.

    Use para confirmar que a seção é real antes de citá-la.
    Opcionalmente verifica se um trecho específico existe na seção.

    Args:
        secao_numero: Número da seção a verificar. Ex: '8.2', '4.5.1'.
        verificar_texto: Texto opcional para verificar se existe na seção.
    """
    _carregar_sistema()

    try:
        docs = _collection.get(
            where={"secao": secao_numero},
            include=["documents", "metadatas"],
        )
    except Exception:
        return json.dumps({
            "secao": secao_numero,
            "encontrada": False,
            "mensagem": f"Erro ao consultar seção '{secao_numero}'.",
        }, ensure_ascii=False)

    if not docs["ids"]:
        return json.dumps({
            "secao": secao_numero,
            "encontrada": False,
            "mensagem": f"Seção '{secao_numero}' não encontrada no manual indexado.",
        }, ensure_ascii=False)

    meta = docs["metadatas"][0]
    texto_completo = "\n".join(docs["documents"])

    resumo = texto_completo[:500]
    if len(texto_completo) > 500:
        resumo += "\n[...truncado]"

    resultado = {
        "secao": secao_numero,
        "encontrada": True,
        "titulo": meta.get("titulo", "").split("\n")[0].strip(),
        "pagina": meta.get("pagina"),
        "fonte": meta.get("fonte", ""),
        "n_trechos": len(docs["ids"]),
        "resumo": resumo,
    }

    if verificar_texto:
        import unicodedata

        def _normalizar(t: str) -> str:
            t = t.lower()
            nfkd = unicodedata.normalize("NFD", t)
            return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")

        resultado["texto_verificado"] = verificar_texto
        resultado["texto_encontrado"] = _normalizar(verificar_texto) in _normalizar(texto_completo)

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def extrair_dados_aih(texto: str) -> str:
    """Extrai dados estruturados de um texto de espelho de AIH.

    Retorna procedimento principal, diagnóstico, CIDs, especialidade, etc.

    Args:
        texto: Texto completo do espelho de AIH copiado do sistema.
    """
    from consulta_manual import extrair_dados_aih as _extrair

    dados = _extrair(texto)
    if dados.get("procedimento_principal"):
        cod, nome = dados["procedimento_principal"]
        dados["procedimento_principal"] = {"codigo": cod, "nome": nome}
    if dados.get("diagnostico_principal"):
        cid, nome = dados["diagnostico_principal"]
        dados["diagnostico_principal"] = {"cid": cid, "nome": nome}
    return json.dumps(dados, ensure_ascii=False, indent=2)


@mcp.tool()
def ler_codigo_critica(numero: int) -> str:
    """Lê o código TypeScript de validação de uma crítica específica.

    Retorna a lógica da função hasCritica extraída do arquivo .ts.
    Útil para entender como a crítica é implementada no sistema.

    Args:
        numero: Número da crítica (ex: 7, 92, 129).
    """
    from validar_critica import ler_codigo_critica as _ler
    from validar_critica import extrair_logica_hasCritica

    codigo = _ler(numero)
    if not codigo:
        return json.dumps(
            {"erro": f"Arquivo critica{numero}.ts não encontrado."},
            ensure_ascii=False,
        )

    logica = extrair_logica_hasCritica(codigo)
    return logica


@mcp.tool()
def contexto_critica(numero: int) -> str:
    """Obtém contexto completo de uma crítica: definição + código + seções do manual.

    Combina definição, código TypeScript e busca no manual para fornecer
    todo o contexto necessário para explicar ou analisar uma crítica.

    Args:
        numero: Número da crítica (ex: 7, 92, 129).
    """
    _carregar_sistema()

    from validar_critica import (
        buscar_manual as _buscar_manual,
        extrair_logica_hasCritica,
        extrair_termos_busca,
        ler_codigo_critica as _ler_codigo,
        ler_definicao_critica,
    )

    definicao = ler_definicao_critica(numero)
    if not definicao:
        return json.dumps({"erro": f"Crítica {numero} não encontrada."}, ensure_ascii=False)

    codigo = _ler_codigo(numero)
    logica = extrair_logica_hasCritica(codigo) if codigo else ""

    queries = extrair_termos_busca(codigo or "", definicao["nome"])
    secoes = _buscar_manual(queries, _model, _collection, n_por_query=3)

    resultado = {
        "definicao": definicao,
        "codigo_hasCritica": logica,
        "secoes_manual": [
            {
                "secao": s["secao"],
                "titulo": s["titulo"],
                "pagina": s["pagina"],
                "relevancia": f"{s['relevancia']:.0%}",
                "texto": s["texto"][:1500],
            }
            for s in secoes[:5]
        ],
    }

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def listar_fontes() -> str:
    """Lista todas as fontes indexadas no banco vetorial (manuais, portarias, etc.)."""
    _carregar_sistema()

    todos = _collection.get(include=["metadatas"])
    fontes: dict[str, int] = {}
    fonte_meta: dict[str, dict] = {}

    for meta in todos["metadatas"]:
        fonte = meta.get("fonte", "?")
        fontes[fonte] = fontes.get(fonte, 0) + 1
        if fonte not in fonte_meta:
            fonte_meta[fonte] = meta

    resultado = []
    for fonte in sorted(fontes.keys()):
        meta = fonte_meta.get(fonte, {})
        resultado.append({
            "fonte": fonte,
            "chunks": fontes[fonte],
            "tipo": meta.get("tipo", "?"),
            "ano": meta.get("ano", "?"),
        })

    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def listar_secoes() -> str:
    """Lista todas as seções únicas do manual indexado com título e página."""
    _carregar_sistema()

    todos = _collection.get(include=["metadatas"])
    secoes_vistas: dict[str, dict] = {}
    for meta in todos["metadatas"]:
        key = meta["secao"]
        if key not in secoes_vistas:
            secoes_vistas[key] = meta

    def _sort_key(x: str) -> list[int]:
        return [int(p) for p in x.split(".") if p.isdigit()]

    resultado = []
    for key in sorted(secoes_vistas.keys(), key=_sort_key):
        meta = secoes_vistas[key]
        resultado.append({
            "secao": meta["secao"],
            "titulo": meta.get("titulo", "").split("\n")[0].strip(),
            "pagina": meta.get("pagina"),
        })

    return json.dumps(resultado, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# SIGTAP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def consultar_procedimento(codigo: str) -> str:
    """Consulta um procedimento SIGTAP pelo código (10 dígitos).

    Retorna nome, valores (SH, SA, SP, total hospitalar), idades, permanência e competência.
    Dados lidos do MinIO (Parquet).

    Args:
        codigo: Código do procedimento (10 dígitos). Ex: '0301010072'.
    """
    from sigtap_client import consultar_procedimento as _consultar

    try:
        resultado = _consultar(codigo)
    except RuntimeError as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)

    if not resultado:
        return json.dumps(
            {"erro": f"Procedimento '{codigo}' não encontrado no SIGTAP."},
            ensure_ascii=False,
        )
    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def buscar_procedimento(nome: str, grupo: str = "") -> str:
    """Busca procedimentos SIGTAP por nome.

    Retorna lista de procedimentos cujo nome contém o termo buscado.
    Filtro opcional por código de grupo (2 primeiros dígitos do código).

    Args:
        nome: Termo de busca no nome do procedimento. Ex: 'colecistectomia', 'parto'.
        grupo: Filtro opcional por prefixo de grupo. Ex: '03' para clínicos, '04' para cirúrgicos.
    """
    from sigtap_client import buscar_procedimentos

    try:
        resultados = buscar_procedimentos(nome, grupo=grupo)
    except RuntimeError as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)

    if not resultados:
        return json.dumps(
            {"mensagem": f"Nenhum procedimento encontrado para '{nome}'."},
            ensure_ascii=False,
        )
    return json.dumps(resultados, ensure_ascii=False, indent=2)


@mcp.tool()
def info_sigtap() -> str:
    """Retorna informações sobre os dados SIGTAP carregados.

    Mostra competência, total de procedimentos e lista de grupos.
    Útil para verificar se os dados estão disponíveis e qual competência está carregada.
    """
    from sigtap_client import info

    try:
        return json.dumps(info(), ensure_ascii=False, indent=2)
    except RuntimeError as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CNES Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def consultar_cnes(codigo_cnes: str) -> str:
    """Consulta dados operacionais de um estabelecimento CNES.

    Retorna leitos (tipos e quantidades SUS), serviços oferecidos,
    habilitações e resumo de profissionais por ocupação.
    Dados lidos do MinIO (Parquet).

    Args:
        codigo_cnes: Código CNES do estabelecimento (7 dígitos). Ex: '2077485'.
    """
    from cnes_client import consultar_cnes as _consultar

    try:
        resultado = _consultar(codigo_cnes)
    except RuntimeError as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)

    if not resultado:
        return json.dumps(
            {"erro": f"CNES '{codigo_cnes}' não encontrado nos dados operacionais."},
            ensure_ascii=False,
        )
    return json.dumps(resultado, ensure_ascii=False, indent=2)


@mcp.tool()
def buscar_profissionais_cnes(codigo_cnes: str, ocupacao: str = "") -> str:
    """Lista profissionais vinculados a um estabelecimento CNES.

    Retorna código de ocupação, identificador SUS e carga horária.
    Filtro opcional por código de ocupação (CBO).

    Args:
        codigo_cnes: Código CNES do estabelecimento (7 dígitos). Ex: '2077485'.
        ocupacao: Código CBO opcional para filtrar. Ex: '225142' (médico cirurgião).
    """
    from cnes_client import buscar_profissionais

    try:
        profs = buscar_profissionais(codigo_cnes, co_ocupacao=ocupacao)
    except RuntimeError as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)

    if not profs:
        msg = f"Nenhum profissional encontrado para CNES '{codigo_cnes}'"
        if ocupacao:
            msg += f" com ocupação '{ocupacao}'"
        return json.dumps({"mensagem": msg + "."}, ensure_ascii=False)
    return json.dumps(profs, ensure_ascii=False, indent=2)


@mcp.tool()
def info_cnes() -> str:
    """Retorna informações sobre os dados CNES carregados.

    Mostra competência e totais de estabelecimentos com leitos, serviços,
    habilitações e profissionais.
    """
    from cnes_client import info

    try:
        return json.dumps(info(), ensure_ascii=False, indent=2)
    except RuntimeError as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="MCP Server Manual SIH/SUS")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transporte MCP (default: stdio)",
    )
    args = parser.parse_args()
    mcp.run(transport=args.transport)


def main_server():
    """Entry point para modo SSE (servidor compartilhado)."""
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
