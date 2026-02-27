"""
Agente inteligente para consulta do Manual SIH/SUS.
Usa Gemini com function calling para raciocinar sobre o manual,
buscando informação relevante e sintetizando respostas.

Uso:
  python agente.py
  python agente.py "como funciona a crítica de compatibilidade CID?"
"""

import json
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types as genai_types
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from consulta_manual import buscar, carregar_api_key, carregar_sistema, extrair_dados_aih

# Camadas de validação (import condicional — falha nunca bloqueia o agente)
try:
    from validar_resposta import exec_verificar_citacao, pos_llm_validar, pre_llm_validar

    _VALIDACAO_DISPONIVEL = True
except ImportError:
    _VALIDACAO_DISPONIVEL = False

console = Console()

MODEL = "gemini-2.0-flash"
MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """\
Você é um agente especialista em faturamento hospitalar SIH/SUS.
Você tem acesso a ferramentas para consultar o Manual Técnico do SIH/SUS, \
buscar informações sobre críticas de validação e analisar AIHs.

Regras:
- SEMPRE use as ferramentas para buscar informações no manual antes de responder. \
  Não invente regras; baseie-se nos trechos retornados pelas ferramentas.
- Cite EXPLICITAMENTE seção e página no formato [Seção X.Y, p.N] ao fundamentar cada afirmação.
- Use a ferramenta verificar_citacao para confirmar que uma seção existe antes de citá-la.
- Se a pergunta envolver uma crítica específica, use buscar_critica para obter detalhes.
- Se a pergunta for genérica sobre o manual, use buscar_manual com termos relevantes.
- Você pode chamar várias ferramentas em sequência para compor uma resposta completa.
- Responda em português. Seja técnico mas acessível.
- Quando não encontrar informação relevante, diga claramente que o manual não cobre o assunto.
- SEMPRE termine a resposta com uma seção "Fontes:" listando todas as seções consultadas.\
"""

# ── Definição de ferramentas para Gemini ──────────────────────────────

TOOLS = genai_types.Tool(
    function_declarations=[
        genai_types.FunctionDeclaration(
            name="buscar_manual",
            description=(
                "Busca semântica no Manual Técnico SIH/SUS e portarias relacionadas. "
                "Retorna trechos relevantes com seção, título, página e score de relevância. "
                "Use para qualquer pergunta sobre regras, procedimentos, campos da AIH, validações."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "query": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Texto de busca em português. Pode ser pergunta, termos-chave ou descrição.",
                    ),
                    "n_resultados": genai_types.Schema(
                        type=genai_types.Type.INTEGER,
                        description="Quantidade de resultados (1-10). Padrão: 5.",
                    ),
                },
                required=["query"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="buscar_critica",
            description=(
                "Busca informações sobre uma crítica específica do SIH/SUS pelo número. "
                "Retorna definição (código, nome, campos) e seções do manual que a fundamentam."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "numero": genai_types.Schema(
                        type=genai_types.Type.INTEGER,
                        description="Número da crítica (ex: 7, 92, 129).",
                    ),
                },
                required=["numero"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="listar_criticas",
            description=(
                "Lista as críticas do SIH/SUS com seus números, códigos e nomes. "
                "Use quando o usuário perguntar quais críticas existem ou precisar encontrar uma por nome."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "filtro": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Filtro opcional por texto no nome. Ex: 'permanência', 'sexo', 'OPM'.",
                    ),
                },
            ),
        ),
        genai_types.FunctionDeclaration(
            name="extrair_dados_aih",
            description=(
                "Extrai dados estruturados de um texto de espelho de AIH. "
                "Retorna procedimento principal, diagnóstico, CIDs, especialidade, etc."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "texto": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Texto completo do espelho de AIH copiado do sistema.",
                    ),
                },
                required=["texto"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="buscar_por_secao",
            description=(
                "Busca uma seção específica do manual pelo número. "
                "Retorna todos os trechos indexados daquela seção. "
                "Use quando já souber o número da seção (ex: '8.6', '4.5.1')."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "secao_numero": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Número da seção do manual. Ex: '4.5', '8.6', '22'.",
                    ),
                },
                required=["secao_numero"],
            ),
        ),
        genai_types.FunctionDeclaration(
            name="verificar_citacao",
            description=(
                "Verifica se uma seção do manual existe no banco de dados antes de citá-la. "
                "Use para confirmar que a seção é real e o conteúdo corresponde ao que você quer citar. "
                "Opcionalmente verifica se um trecho específico existe na seção."
            ),
            parameters=genai_types.Schema(
                type=genai_types.Type.OBJECT,
                properties={
                    "secao_numero": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Número da seção a verificar. Ex: '8.2', '4.5.1'.",
                    ),
                    "verificar_texto": genai_types.Schema(
                        type=genai_types.Type.STRING,
                        description="Texto opcional para verificar se existe na seção.",
                    ),
                },
                required=["secao_numero"],
            ),
        ),
    ]
)


# ── Executores de ferramentas ──────────────────────────────────────────


def exec_buscar_manual(args: dict, model, collection) -> str:
    query = args["query"]
    n = min(args.get("n_resultados", 5), 10)
    resultados = buscar(query, model, collection, n_resultados=n)

    # Camada 1: validação pré-LLM (filtrar ruído, reformular se necessário)
    aviso = None
    if _VALIDACAO_DISPONIVEL:
        try:
            resultados, aviso = pre_llm_validar(
                resultados, query, model, collection, buscar,
            )
        except Exception:
            pass  # nunca bloquear

    saida = []
    for r in resultados:
        texto = r["texto"]
        if len(texto) > 1500:
            texto = texto[:1500] + "\n[...truncado]"
        saida.append({
            "secao": r["metadata"]["secao"],
            "titulo": r["metadata"]["titulo"].split("\n")[0].strip(),
            "pagina": r["metadata"]["pagina"],
            "relevancia": f"{r['score']:.0%}",
            "texto": texto,
        })

    # Prepend aviso de qualidade para o Gemini saber
    if aviso:
        saida.insert(0, {"aviso": aviso})

    return json.dumps(saida, ensure_ascii=False)


def exec_buscar_critica(args: dict, collection, mapeamento: list) -> str:
    numero = args["numero"]

    # Dados do mapeamento pré-computado
    entrada = next((m for m in mapeamento if m["numero"] == numero), None)
    if not entrada:
        return json.dumps({"erro": f"Crítica {numero} não encontrada."}, ensure_ascii=False)

    resultado = {
        "numero": entrada["numero"],
        "codigo": entrada["codigo"],
        "nome": entrada["nome"],
        "secoes_manual": entrada.get("secoes_manual", []),
    }

    # Tentar carregar definição detalhada do .ts
    try:
        from validar_critica import ler_definicao_critica
        defn = ler_definicao_critica(numero)
        if defn:
            resultado["campos"] = defn.get("campos", [])
    except Exception:
        pass

    # Buscar texto das seções referenciadas
    for secao_info in resultado["secoes_manual"]:
        try:
            docs = collection.get(
                where={"secao": secao_info["secao"]},
                include=["documents", "metadatas"],
            )
            if docs["documents"]:
                texto = docs["documents"][0]
                if len(texto) > 1200:
                    texto = texto[:1200] + "\n[...truncado]"
                secao_info["texto"] = texto
        except Exception:
            pass

    return json.dumps(resultado, ensure_ascii=False)


def exec_listar_criticas(args: dict, mapeamento: list) -> str:
    filtro = args.get("filtro", "").lower()
    criticas = [
        {"numero": m["numero"], "codigo": m["codigo"], "nome": m["nome"]}
        for m in mapeamento
        if not filtro or filtro in m["nome"].lower()
    ]
    return json.dumps(criticas, ensure_ascii=False)


def exec_extrair_dados_aih(args: dict) -> str:
    dados = extrair_dados_aih(args["texto"])
    # Converter tuples para dicts serializáveis
    if dados.get("procedimento_principal"):
        cod, nome = dados["procedimento_principal"]
        dados["procedimento_principal"] = {"codigo": cod, "nome": nome}
    if dados.get("diagnostico_principal"):
        cid, nome = dados["diagnostico_principal"]
        dados["diagnostico_principal"] = {"cid": cid, "nome": nome}
    return json.dumps(dados, ensure_ascii=False)


def exec_buscar_por_secao(args: dict, collection) -> str:
    secao = args["secao_numero"]
    docs = collection.get(
        where={"secao": secao},
        include=["documents", "metadatas"],
    )
    if not docs["ids"]:
        return json.dumps({"erro": f"Seção '{secao}' não encontrada."}, ensure_ascii=False)

    resultados = []
    for i in range(len(docs["ids"])):
        texto = docs["documents"][i]
        if len(texto) > 1500:
            texto = texto[:1500] + "\n[...truncado]"
        meta = docs["metadatas"][i]
        resultados.append({
            "titulo": meta.get("titulo", "").split("\n")[0].strip(),
            "pagina": meta.get("pagina"),
            "fonte": meta.get("fonte", ""),
            "texto": texto,
        })
    return json.dumps(resultados, ensure_ascii=False)


def executar_ferramenta(nome: str, args: dict, model, collection, mapeamento: list) -> str:
    """Despacha a execução para a ferramenta correta."""
    try:
        if nome == "buscar_manual":
            return exec_buscar_manual(args, model, collection)
        elif nome == "buscar_critica":
            return exec_buscar_critica(args, collection, mapeamento)
        elif nome == "listar_criticas":
            return exec_listar_criticas(args, mapeamento)
        elif nome == "extrair_dados_aih":
            return exec_extrair_dados_aih(args)
        elif nome == "buscar_por_secao":
            return exec_buscar_por_secao(args, collection)
        elif nome == "verificar_citacao" and _VALIDACAO_DISPONIVEL:
            return exec_verificar_citacao(args, collection)
        else:
            return json.dumps({"erro": f"Ferramenta desconhecida: {nome}"})
    except Exception as e:
        return json.dumps({"erro": str(e)}, ensure_ascii=False)


# ── Loop do agente ─────────────────────────────────────────────────────


def processar_turno(chat, pergunta: str, embed_model, collection, mapeamento: list):
    """Executa um turno completo: envia mensagem, processa function calls, exibe resposta final."""
    _TOOLS_BUSCA = {"buscar_manual", "buscar_critica", "buscar_por_secao"}
    contexto_rag_acumulado: list[str] = []

    response = chat.send_message(pergunta)

    for _ in range(MAX_TOOL_ROUNDS):
        if not response.candidates:
            console.print("[red]Resposta bloqueada pelo modelo.[/red]")
            return

        parts = response.candidates[0].content.parts

        # Identificar function calls na resposta
        function_calls = [p for p in parts if p.function_call]

        if not function_calls:
            # Resposta final — exibir texto
            texto_resposta = response.text or ""
            if texto_resposta:
                console.print()
                console.print(texto_resposta)

            # Camada 2: validação pós-LLM (citações + grounding)
            if _VALIDACAO_DISPONIVEL and contexto_rag_acumulado and texto_resposta:
                try:
                    contexto_str = "\n---\n".join(contexto_rag_acumulado)
                    validacao = pos_llm_validar(
                        texto_resposta, contexto_str, collection,
                    )
                    if validacao["rodape"]:
                        console.print()
                        console.print(
                            Panel(
                                validacao["rodape"],
                                title="[dim]Verificação[/dim]",
                                border_style="dim",
                                padding=(0, 1),
                            )
                        )
                    if validacao["tem_problemas"]:
                        console.print(
                            "[yellow]Atenção: algumas citações podem estar "
                            "imprecisas. Consulte o manual para confirmação.[/yellow]"
                        )
                except Exception:
                    pass  # nunca bloquear a resposta
            return

        # Function calls — executar ferramentas
        func_responses = []
        for fc_part in function_calls:
            name = fc_part.function_call.name
            args = dict(fc_part.function_call.args) if fc_part.function_call.args else {}
            console.print(f"  [dim]⚙ {name}({_resumir_args(args)})[/dim]")
            resultado = executar_ferramenta(
                name, args, embed_model, collection, mapeamento,
            )
            # Acumular contexto RAG para verificação pós-LLM
            if name in _TOOLS_BUSCA:
                contexto_rag_acumulado.append(resultado)

            func_responses.append(
                genai_types.Part.from_function_response(
                    name=name,
                    response={"resultado": resultado},
                )
            )

        response = chat.send_message(func_responses)

    console.print("[yellow]Limite de chamadas de ferramentas atingido.[/yellow]")


def _resumir_args(args: dict) -> str:
    """Resumo curto dos argumentos para exibição."""
    partes = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > 60:
            v = v[:57] + "..."
        partes.append(f"{k}={v!r}")
    return ", ".join(partes)


def conversar(gemini_client, embed_model, collection, mapeamento: list):
    """REPL principal do agente."""
    chat = gemini_client.chats.create(
        model=MODEL,
        config=genai_types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[TOOLS],
            max_output_tokens=MAX_TOKENS,
        ),
    )

    console.print(
        Panel(
            "[bold]Pergunte qualquer coisa sobre o Manual SIH/SUS.[/bold]\n\n"
            "Exemplos:\n"
            "  [cyan]Quais regras se aplicam a politraumatizado?[/cyan]\n"
            "  [cyan]O que a crítica 7 verifica?[/cyan]\n"
            "  [cyan]Quais críticas envolvem compatibilidade de sexo?[/cyan]\n"
            "  [cyan]Qual o limite de diárias de acompanhante em UTI?[/cyan]\n\n"
            "[dim]Digite 'sair' para encerrar.[/dim]",
            title="[bold blue]Agente SIH/SUS[/bold blue]",
            border_style="blue",
        )
    )

    while True:
        try:
            pergunta = Prompt.ask("\n[bold blue]Pergunta[/bold blue]")
        except (KeyboardInterrupt, EOFError):
            break

        if not pergunta.strip():
            continue
        if pergunta.strip().lower() in ("sair", "exit", "quit", "q"):
            break

        with console.status("[dim]Pensando...[/dim]"):
            processar_turno(chat, pergunta, embed_model, collection, mapeamento)


# ── Main ───────────────────────────────────────────────────────────────


def main():
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    console.print("\n[bold blue]Agente SIH/SUS[/bold blue] — Consulta inteligente do Manual\n")

    api_key = carregar_api_key()
    if not api_key:
        console.print("[red]API key do Gemini não encontrada.[/red]")
        console.print("[dim]Configure via GEMINI_API_KEY ou ~/.config/google/api_key[/dim]")
        sys.exit(1)

    gemini_client = genai.Client(api_key=api_key)

    embed_model, collection = carregar_sistema()

    mapeamento_path = Path(__file__).parent / "data" / "mapeamento_criticas_manual.json"
    if mapeamento_path.exists():
        mapeamento = json.loads(mapeamento_path.read_text(encoding="utf-8"))
        console.print(f"[green]{len(mapeamento)} críticas carregadas.[/green]\n")
    else:
        mapeamento = []
        console.print("[yellow]Mapeamento de críticas não encontrado (funcionalidade reduzida).[/yellow]\n")

    conversar(gemini_client, embed_model, collection, mapeamento)
    console.print("\n[dim]Até logo![/dim]")


if __name__ == "__main__":
    main()
