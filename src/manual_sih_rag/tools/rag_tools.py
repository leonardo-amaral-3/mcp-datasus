"""Tools MCP para consulta ao Manual SIH/SUS via RAG (busca semantica)."""

from __future__ import annotations

import json
import unicodedata
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

RAGLoader = Callable[[], tuple[Any, Any, list]]


def register(mcp: "FastMCP", get_rag: RAGLoader) -> None:
    """Registra 10 tools de busca no manual via RAG.

    Args:
        get_rag: callable que retorna (model, collection, mapeamento).
    """

    @mcp.tool()
    def buscar_manual(query: str, n_resultados: int = 5) -> str:
        """Busca semantica no Manual Tecnico SIH/SUS e portarias relacionadas.

        Retorna trechos relevantes com secao, titulo, pagina e score de relevancia.
        Use para qualquer pergunta sobre regras, procedimentos, campos da AIH, validacoes.

        Args:
            query: Texto de busca em portugues. Pode ser pergunta, termos-chave ou descricao.
            n_resultados: Quantidade de resultados (1-10). Padrao: 5.
        """
        model, collection, _ = get_rag()
        from consulta_manual import buscar

        n = min(max(n_resultados, 1), 10)
        resultados = buscar(query, model, collection, n_resultados=n)

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
        """Busca informacoes sobre uma critica especifica do SIH/SUS pelo numero.

        Retorna definicao (codigo, nome, campos) e secoes do manual que a fundamentam.

        Args:
            numero: Numero da critica (ex: 7, 92, 129).
        """
        _, collection, mapeamento = get_rag()

        if not mapeamento:
            return json.dumps({"erro": "Mapeamento de criticas nao carregado."}, ensure_ascii=False)

        entrada = next((m for m in mapeamento if m["numero"] == numero), None)
        if not entrada:
            return json.dumps({"erro": f"Critica {numero} nao encontrada."}, ensure_ascii=False)

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
                docs = collection.get(
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
        """Lista as criticas do SIH/SUS com seus numeros, codigos e nomes.

        Use quando o usuario perguntar quais criticas existem ou precisar encontrar uma por nome.

        Args:
            filtro: Filtro opcional por texto no nome. Ex: 'permanencia', 'sexo', 'OPM'.
        """
        _, _, mapeamento = get_rag()
        filtro_lower = filtro.lower()
        criticas = [
            {"numero": m["numero"], "codigo": m["codigo"], "nome": m["nome"]}
            for m in (mapeamento or [])
            if not filtro_lower or filtro_lower in m["nome"].lower()
        ]
        return json.dumps(criticas, ensure_ascii=False, indent=2)

    @mcp.tool()
    def buscar_por_secao(secao_numero: str) -> str:
        """Busca uma secao especifica do manual pelo numero.

        Retorna todos os trechos indexados daquela secao.
        Use quando ja souber o numero da secao (ex: '8.6', '4.5.1').

        Args:
            secao_numero: Numero da secao do manual. Ex: '4.5', '8.6', '22'.
        """
        _, collection, _ = get_rag()
        docs = collection.get(
            where={"secao": secao_numero},
            include=["documents", "metadatas"],
        )
        if not docs["ids"]:
            return json.dumps(
                {"erro": f"Secao '{secao_numero}' nao encontrada."},
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
        """Verifica se uma secao do manual existe no banco de dados.

        Use para confirmar que a secao e real antes de cita-la.
        Opcionalmente verifica se um trecho especifico existe na secao.

        Args:
            secao_numero: Numero da secao a verificar. Ex: '8.2', '4.5.1'.
            verificar_texto: Texto opcional para verificar se existe na secao.
        """
        _, collection, _ = get_rag()

        try:
            docs = collection.get(
                where={"secao": secao_numero},
                include=["documents", "metadatas"],
            )
        except Exception:
            return json.dumps({
                "secao": secao_numero,
                "encontrada": False,
                "mensagem": f"Erro ao consultar secao '{secao_numero}'.",
            }, ensure_ascii=False)

        if not docs["ids"]:
            return json.dumps({
                "secao": secao_numero,
                "encontrada": False,
                "mensagem": f"Secao '{secao_numero}' nao encontrada no manual indexado.",
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
            def _normalizar(t: str) -> str:
                t = t.lower()
                nfkd = unicodedata.normalize("NFD", t)
                return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")

            resultado["texto_verificado"] = verificar_texto
            resultado["texto_encontrado"] = (
                _normalizar(verificar_texto) in _normalizar(texto_completo)
            )

        return json.dumps(resultado, ensure_ascii=False, indent=2)

    @mcp.tool()
    def extrair_dados_aih(texto: str) -> str:
        """Extrai dados estruturados de um texto de espelho de AIH.

        Retorna procedimento principal, diagnostico, CIDs, especialidade, etc.

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
        """Le o codigo TypeScript de validacao de uma critica especifica.

        Retorna a logica da funcao hasCritica extraida do arquivo .ts.
        Util para entender como a critica e implementada no sistema.

        Args:
            numero: Numero da critica (ex: 7, 92, 129).
        """
        from validar_critica import ler_codigo_critica as _ler
        from validar_critica import extrair_logica_hasCritica

        codigo = _ler(numero)
        if not codigo:
            return json.dumps(
                {"erro": f"Arquivo critica{numero}.ts nao encontrado."},
                ensure_ascii=False,
            )
        return extrair_logica_hasCritica(codigo)

    @mcp.tool()
    def contexto_critica(numero: int) -> str:
        """Obtem contexto completo de uma critica: definicao + codigo + secoes do manual.

        Combina definicao, codigo TypeScript e busca no manual para fornecer
        todo o contexto necessario para explicar ou analisar uma critica.

        Args:
            numero: Numero da critica (ex: 7, 92, 129).
        """
        model, collection, _ = get_rag()

        from validar_critica import (
            buscar_manual as _buscar_manual,
            extrair_logica_hasCritica,
            extrair_termos_busca,
            ler_codigo_critica as _ler_codigo,
            ler_definicao_critica,
        )

        definicao = ler_definicao_critica(numero)
        if not definicao:
            return json.dumps(
                {"erro": f"Critica {numero} nao encontrada."},
                ensure_ascii=False,
            )

        codigo = _ler_codigo(numero)
        logica = extrair_logica_hasCritica(codigo) if codigo else ""

        queries = extrair_termos_busca(codigo or "", definicao["nome"])
        secoes = _buscar_manual(queries, model, collection, n_por_query=3)

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
        _, collection, _ = get_rag()

        todos = collection.get(include=["metadatas"])
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
        """Lista todas as secoes unicas do manual indexado com titulo e pagina."""
        _, collection, _ = get_rag()

        todos = collection.get(include=["metadatas"])
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
