"""Critica analysis agent — confronts code with Manual SIH/SUS.

Extracted from root analisar_critica.py — core functions only (no CLI main).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validar import (
    buscar_manual,
    extrair_logica_hasCritica,
    extrair_termos_busca,
    ler_codigo_critica,
    ler_definicao_critica,
)

PROMPT_SISTEMA = """\
Voce e um auditor especialista em faturamento hospitalar SIH/SUS.
Sua tarefa e confrontar o CODIGO DE UMA CRITICA (regra de validacao implementada em TypeScript) \
com os TRECHOS DO MANUAL TECNICO SIH/SUS que fundamentam essa regra.

Analise com rigor tecnico e responda SEMPRE neste formato:

## Resumo da Regra
(O que a critica valida, em 2-3 frases simples)

## O que o Codigo Faz
(Descreva a logica implementada passo a passo, citando variaveis e condicoes)

## O que o Manual Diz
(Resuma os trechos relevantes do manual, citando secao e pagina)

## Parecer de Conformidade

**Veredicto: CONFORME | PARCIALMENTE CONFORME | NAO CONFORME**

### Pontos Conformes
- (liste o que o codigo implementa corretamente segundo o manual)

### Lacunas no Codigo
- (regras do manual que o codigo NAO implementa ou implementa de forma incompleta)

### Excesso no Codigo
- (validacoes que o codigo faz mas que NAO tem fundamentacao clara no manual)

### Riscos
- (consequencias praticas das lacunas: glosas indevidas, rejeicoes incorretas, etc.)

## Recomendacoes
- (acoes concretas para corrigir lacunas ou excessos, se houver)

Seja preciso. Cite secoes e paginas do manual. Nao invente regras que nao estao nos trechos fornecidos.\
"""


def montar_prompt(definicao: dict, codigo: str, secoes_manual: list[dict]) -> str:
    """Build prompt with code + manual for Gemini analysis."""
    logica = extrair_logica_hasCritica(codigo)

    secoes_texto = ""
    for i, s in enumerate(secoes_manual[:7]):
        secoes_texto += (
            f"\n--- Trecho {i+1}: Secao {s['secao']} - {s['titulo']} "
            f"(pagina {s['pagina']}, relevancia {s['relevancia']:.0%}) ---\n"
            f"{s['texto']}\n"
        )

    return f"""\
# Critica {definicao['numero']} — {definicao['nome']}
Codigo SIH: {definicao['codigo']}
Campos validados: {', '.join(definicao['campos'])}

## CODIGO DA CRITICA (TypeScript)

```typescript
{logica}
```

## CODIGO COMPLETO (com imports e helpers)

```typescript
{codigo}
```

## TRECHOS DO MANUAL SIH/SUS
{secoes_texto}

Analise a conformidade do codigo com o manual.\
"""


def analisar_uma_critica(
    numero: int,
    model: Any,
    collection: Any,
    api_key: str,
    salvar: bool = False,
    output_dir: Path | None = None,
) -> dict | None:
    """Execute full analysis of a single critica. Returns result dict or None."""
    from rich.console import Console
    console = Console()

    definicao = ler_definicao_critica(numero)
    if not definicao:
        console.print(f"[red]Critica {numero} nao encontrada em criticas.ts[/red]")
        return None

    codigo = ler_codigo_critica(numero)
    if not codigo:
        console.print(f"[red]Arquivo critica{numero}.ts nao encontrado[/red]")
        return None

    console.print(f"[dim]Buscando secoes relevantes do manual...[/dim]")
    queries = extrair_termos_busca(codigo, definicao["nome"])
    secoes = buscar_manual(queries, model, collection, n_por_query=3)

    console.print(f"[dim]{len(secoes)} trechos encontrados — enviando para analise...[/dim]")

    prompt = montar_prompt(definicao, codigo, secoes)

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    chat = client.chats.create(
        model="gemini-2.0-flash",
        config=genai_types.GenerateContentConfig(
            system_instruction=PROMPT_SISTEMA,
            max_output_tokens=4096,
        ),
    )

    resposta = ""
    console.print()
    for chunk in chat.send_message_stream(prompt):
        if chunk.text:
            resposta += chunk.text
            console.print(chunk.text, end="", highlight=False)
    console.print()

    resultado = {
        "critica": numero,
        "codigo_sih": definicao["codigo"],
        "nome": definicao["nome"],
        "campos": definicao["campos"],
        "secoes_consultadas": [
            {"secao": s["secao"], "titulo": s["titulo"], "pagina": s["pagina"], "relevancia": s["relevancia"]}
            for s in secoes[:7]
        ],
        "analise": resposta,
    }

    if salvar and output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"analise_critica_{numero}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        md_path = output_dir / f"analise_critica_{numero}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# Analise Critica {numero} — {definicao['nome']}\n\n")
            f.write(f"Codigo SIH: {definicao['codigo']}  \n")
            f.write(f"Campos: {', '.join(definicao['campos'])}  \n\n")
            f.write(resposta)

        console.print(f"\n[green]Salvo em: {output_path}[/green]")

    return resultado
