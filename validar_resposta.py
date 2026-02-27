"""
Módulo de validação de respostas do agente RAG SIH/SUS.

Implementa 3 camadas de validação:
  1. Pré-LLM: filtra ruído e reformula queries com baixa relevância
  2. Pós-LLM: verifica citações e grounding da resposta do Gemini
  3. Auto-verificação: tool para o Gemini confirmar seções antes de citar

Uso:
  from validar_resposta import pre_llm_validar, pos_llm_validar, exec_verificar_citacao
"""

import json
import re
import unicodedata
from typing import Any

from google import genai
from google.genai import types as genai_types

# ---------------------------------------------------------------------------
# Camada 1: Pré-LLM
# ---------------------------------------------------------------------------

_RELEVANCIA_THRESHOLD = 0.35
_REFORMULACAO_THRESHOLD = 0.40


def filtrar_por_relevancia(
    resultados: list[dict], threshold: float = _RELEVANCIA_THRESHOLD
) -> list[dict]:
    """Remove resultados com score abaixo do threshold.

    Se todos forem removidos, retorna os originais para não ficar sem contexto.
    """
    if not resultados:
        return resultados
    filtrados = [r for r in resultados if r.get("score", 0) >= threshold]
    return filtrados if filtrados else resultados


def reformular_query(query_original: str) -> list[str]:
    """Gera reformulações da query para retry quando resultados são fracos."""
    queries = [query_original]
    q_lower = query_original.lower()

    # Estratégia 1: adicionar termos de domínio se ausentes
    termos_dominio = ["SIH", "SUS", "manual", "AIH", "internação"]
    tem_dominio = any(t.lower() in q_lower for t in termos_dominio)
    if not tem_dominio:
        queries.append(f"{query_original} SIH/SUS regras manual")

    # Estratégia 2: expandir siglas comuns
    _siglas = {
        "opm": "órteses próteses materiais especiais",
        "cid": "classificação internacional doenças diagnóstico",
        "cbo": "classificação brasileira ocupações profissional",
        "cnes": "cadastro nacional estabelecimentos saúde",
        "uti": "unidade terapia intensiva",
        "aih": "autorização internação hospitalar",
    }
    for sigla, expansao in _siglas.items():
        if re.search(rf"\b{sigla}\b", q_lower):
            queries.append(f"{query_original} {expansao}")
            break

    # Estratégia 3: extrair keywords substantivas (remover stopwords)
    _stops = frozenset(
        "a o e de do da dos das em no na nos nas um uma uns umas para por com como "
        "que se ou ao aos as os seu sua seus suas qual quais".split()
    )
    palavras = [p for p in q_lower.split() if p not in _stops and len(p) >= 3]
    if len(palavras) >= 2 and len(palavras) != len(q_lower.split()):
        queries.append(" ".join(palavras))

    # Deduplica preservando ordem
    vistos: set[str] = set()
    dedup: list[str] = []
    for q in queries:
        q_norm = q.strip()
        if q_norm and q_norm not in vistos:
            vistos.add(q_norm)
            dedup.append(q_norm)

    return dedup


def pre_llm_validar(
    resultados: list[dict],
    query: str,
    model: Any,
    collection: Any,
    buscar_fn: Any,
) -> tuple[list[dict], str | None]:
    """Orquestrador da Camada 1: filtra e reformula se necessário.

    Retorna (resultados_validados, aviso_ou_None).
    """
    # Passo 1: filtrar
    filtrados = filtrar_por_relevancia(resultados)

    # Passo 2: verificar qualidade
    melhor_score = max((r.get("score", 0) for r in filtrados), default=0)

    # Se qualidade baixa, reformular e rebuscar
    if melhor_score < _REFORMULACAO_THRESHOLD and buscar_fn is not None:
        alternativas = reformular_query(query)
        todos = list(filtrados)
        ids_vistos = {r.get("id") for r in todos}

        for alt_query in alternativas[1:]:  # pular a original
            novos = buscar_fn(alt_query, model, collection, n_resultados=5)
            for r in novos:
                if r.get("id") not in ids_vistos:
                    ids_vistos.add(r.get("id"))
                    todos.append(r)

        todos.sort(key=lambda x: x.get("score", 0), reverse=True)
        filtrados = filtrar_por_relevancia(todos)
        melhor_score = max((r.get("score", 0) for r in filtrados), default=0)

    # Passo 3: anotar qualidade
    aviso = None
    if melhor_score < _REFORMULACAO_THRESHOLD:
        aviso = (
            f"[AVISO: Resultados de baixa relevância (melhor score: {melhor_score:.0%}). "
            "A informação pode ser imprecisa ou incompleta.]"
        )
    elif len(filtrados) < 2:
        aviso = "[AVISO: Poucos trechos relevantes encontrados para esta consulta.]"

    return filtrados, aviso


# ---------------------------------------------------------------------------
# Camada 2: Pós-LLM
# ---------------------------------------------------------------------------

_CITACAO_PATTERNS = [
    # [Seção X.Y, p.N]
    re.compile(
        r"\[Se[cç][aã]o\s+(\d+(?:\.\d+)*)\s*,\s*p\.?\s*(\d+)\]",
        re.IGNORECASE,
    ),
    # Seção X.Y (página N) ou Seção X.Y, página N
    re.compile(
        r"Se[cç][aã]o\s+(\d+(?:\.\d+)*)\s*(?:,\s*|\()p[aá]gina\s+(\d+)\)?",
        re.IGNORECASE,
    ),
    # Seção X.Y sem página
    re.compile(
        r"Se[cç][aã]o\s+(\d+(?:\.\d+)*)",
        re.IGNORECASE,
    ),
]


def extrair_citacoes(texto_resposta: str) -> list[dict]:
    """Extrai citações de seção/página da resposta do Gemini."""
    citacoes: list[dict] = []
    vistos: set[str] = set()

    for pattern in _CITACAO_PATTERNS:
        for m in pattern.finditer(texto_resposta):
            secao = m.group(1)
            pagina = None
            if m.lastindex and m.lastindex >= 2:
                try:
                    pagina = int(m.group(2))
                except (ValueError, TypeError, IndexError):
                    pass

            chave = f"{secao}:{pagina}"
            if chave not in vistos:
                vistos.add(chave)
                citacoes.append({
                    "secao": secao,
                    "pagina": pagina,
                    "texto_original": m.group(0),
                })

    return citacoes


def verificar_citacao_no_db(citacao: dict, collection: Any) -> dict:
    """Verifica se uma citação existe no ChromaDB."""
    secao = citacao["secao"]
    try:
        docs = collection.get(
            where={"secao": secao},
            include=["metadatas"],
        )
    except Exception:
        return {"secao": secao, "existe": False, "erro": "falha na consulta"}

    if not docs["ids"]:
        return {"secao": secao, "existe": False}

    meta = docs["metadatas"][0]
    pagina_real = meta.get("pagina")
    pagina_citada = citacao.get("pagina")

    pagina_confere = True
    if pagina_citada is not None and pagina_real is not None:
        try:
            pagina_confere = int(pagina_citada) == int(pagina_real)
        except (ValueError, TypeError):
            pagina_confere = False

    return {
        "secao": secao,
        "existe": True,
        "titulo": meta.get("titulo", "").split("\n")[0].strip(),
        "pagina_real": pagina_real,
        "pagina_citada": pagina_citada,
        "pagina_confere": pagina_confere,
    }


def verificar_todas_citacoes(texto_resposta: str, collection: Any) -> list[dict]:
    """Extrai e verifica todas as citações da resposta."""
    citacoes = extrair_citacoes(texto_resposta)
    return [verificar_citacao_no_db(c, collection) for c in citacoes]


_GROUNDING_SYSTEM = """\
Você é um verificador de qualidade de respostas sobre o Manual SIH/SUS.
Analise a RESPOSTA e compare com o CONTEXTO fornecido (trechos do manual).
Para cada afirmação factual na resposta, classifique como:
- "fundamentado": tem suporte direto no contexto
- "inferência": inferência razoável a partir do contexto
- "sem_fonte": não tem suporte no contexto

Responda APENAS em JSON:
{"claims": [{"texto": "afirmação resumida", "classificacao": "fundamentado|inferência|sem_fonte"}], "score_geral": 0.0-1.0}

score_geral = proporção de claims fundamentados + 0.5 * inferenciais."""


def grounding_check(
    texto_resposta: str,
    contexto_rag: str,
) -> dict:
    """Verifica grounding da resposta via Gemini Flash.

    Retorna {"claims": [...], "score_geral": float}.
    Em caso de erro, retorna {"claims": [], "score_geral": -1, "erro": str}.
    """
    # Truncar contexto para manter custo baixo
    if len(contexto_rag) > 8000:
        contexto_rag = contexto_rag[:8000] + "\n[...truncado]"

    try:
        import os
        from pathlib import Path
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            key_file = Path.home() / ".config" / "google" / "api_key"
            if key_file.exists():
                key = key_file.read_text().strip()
        if not key:
            return {"claims": [], "score_geral": -1, "erro": "no_api_key"}

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"## RESPOSTA\n{texto_resposta}\n\n## CONTEXTO\n{contexto_rag}",
            config=genai_types.GenerateContentConfig(
                system_instruction=_GROUNDING_SYSTEM,
                max_output_tokens=1024,
            ),
        )

        texto_gemini = response.text

        # Tentar parsear JSON direto
        try:
            return json.loads(texto_gemini)
        except json.JSONDecodeError:
            pass

        # Fallback: extrair JSON do texto
        m = re.search(r"\{.*\}", texto_gemini, re.DOTALL)
        if m:
            return json.loads(m.group(0))

        return {"claims": [], "score_geral": -1, "erro": "json_parse_error"}

    except Exception as e:
        return {"claims": [], "score_geral": -1, "erro": str(e)}


def formatar_rodape_verificacao(
    citacoes: list[dict], grounding: dict
) -> str:
    """Formata o rodapé de verificação para exibição."""
    partes: list[str] = []

    # Seção 1: Citações
    if citacoes:
        linhas = ["Citações verificadas:"]
        for c in citacoes:
            secao = c["secao"]
            if c.get("existe"):
                status = "OK"
                if not c.get("pagina_confere", True):
                    status = f"OK (p.real={c.get('pagina_real')})"
            else:
                status = "NAO ENCONTRADA"
            linhas.append(f"  [{secao}] {status}")
        partes.append("\n".join(linhas))
    else:
        partes.append("Nenhuma citação de seção detectada na resposta.")

    # Seção 2: Grounding
    score = grounding.get("score_geral", -1)
    if score >= 0:
        claims = grounding.get("claims", [])
        n_fund = sum(1 for c in claims if c.get("classificacao") == "fundamentado")
        n_inf = sum(1 for c in claims if c.get("classificacao") == "inferência")
        n_sem = sum(1 for c in claims if c.get("classificacao") == "sem_fonte")
        total = n_fund + n_inf + n_sem

        partes.append(
            f"Grounding: {score:.0%} "
            f"({n_fund} fundamentadas, {n_inf} inferências, {n_sem} sem fonte"
            f" — {total} afirmações)"
        )
    else:
        erro = grounding.get("erro", "desconhecido")
        partes.append(f"Grounding: verificação indisponível ({erro})")

    return "\n".join(partes)


def pos_llm_validar(
    texto_resposta: str,
    contexto_rag: str,
    collection: Any,
) -> dict:
    """Orquestrador da Camada 2: verifica citações e grounding.

    Retorna {"citacoes", "grounding", "rodape", "tem_problemas"}.
    """
    # Verificar citações
    citacoes = verificar_todas_citacoes(texto_resposta, collection)

    # Grounding check (Gemini) — wrapped para nunca bloquear
    try:
        grounding = grounding_check(texto_resposta, contexto_rag)
    except Exception:
        grounding = {"claims": [], "score_geral": -1, "erro": "exception"}

    # Montar rodapé
    rodape = formatar_rodape_verificacao(citacoes, grounding)

    # Detectar problemas
    tem_problemas = False
    if any(not c.get("existe") for c in citacoes):
        tem_problemas = True

    score = grounding.get("score_geral", -1)
    if 0 <= score < 0.5:
        tem_problemas = True

    claims = grounding.get("claims", [])
    n_sem = sum(1 for c in claims if c.get("classificacao") == "sem_fonte")
    if claims and n_sem / len(claims) > 0.3:
        tem_problemas = True

    return {
        "citacoes": citacoes,
        "grounding": grounding,
        "rodape": rodape,
        "tem_problemas": tem_problemas,
    }


# ---------------------------------------------------------------------------
# Camada 3: Tool de auto-verificação
# ---------------------------------------------------------------------------


def exec_verificar_citacao(args: dict, collection: Any) -> str:
    """Executor da tool verificar_citacao — o Gemini chama para double-check."""
    secao = args.get("secao_numero", "")
    verificar_texto = args.get("verificar_texto", "")

    try:
        docs = collection.get(
            where={"secao": secao},
            include=["documents", "metadatas"],
        )
    except Exception:
        return json.dumps({
            "secao": secao,
            "encontrada": False,
            "mensagem": f"Erro ao consultar seção '{secao}'.",
        }, ensure_ascii=False)

    if not docs["ids"]:
        return json.dumps({
            "secao": secao,
            "encontrada": False,
            "mensagem": f"Seção '{secao}' não encontrada no manual indexado.",
        }, ensure_ascii=False)

    textos = docs["documents"]
    meta = docs["metadatas"][0]
    texto_completo = "\n".join(textos)

    resumo = texto_completo[:500]
    if len(texto_completo) > 500:
        resumo += "\n[...truncado]"

    resultado = {
        "secao": secao,
        "encontrada": True,
        "titulo": meta.get("titulo", "").split("\n")[0].strip(),
        "pagina": meta.get("pagina"),
        "fonte": meta.get("fonte", ""),
        "n_trechos": len(docs["ids"]),
        "resumo": resumo,
    }

    if verificar_texto:
        # Normalizar para busca case-insensitive + sem acentos
        def normalizar(t: str) -> str:
            t = t.lower()
            nfkd = unicodedata.normalize("NFD", t)
            return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn")

        resultado["texto_verificado"] = verificar_texto
        resultado["texto_encontrado"] = normalizar(verificar_texto) in normalizar(texto_completo)

    return json.dumps(resultado, ensure_ascii=False)
