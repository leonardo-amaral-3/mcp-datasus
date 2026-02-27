"""MCP tools para auditoria de faturamento hospitalar."""

from __future__ import annotations

from typing import Any


# ── Rótulos legíveis para campos comuns ──────────────────────────

_ROTULOS: dict[str, str] = {
    # Status
    "conforme": "Conforme",
    "valido": "Válido",
    "atendido": "Atendido",
    "aplicavel": "Aplicável",
    "erro": "Erro",
    "msg": "Mensagem",
    "resumo": "Resumo",
    # Procedimento
    "codigo": "Código",
    "nome": "Nome",
    "co_procedimento": "Cód. Procedimento",
    "no_procedimento": "Nome Procedimento",
    "tp_complexidade": "Complexidade",
    "tp_sexo": "Restrição Sexo",
    "descricao": "Descrição",
    # Valores
    "vl_sh": "Valor SH",
    "vl_sa": "Valor SA",
    "vl_sp": "Valor SP",
    "vl_total": "Valor Total",
    "vl_total_hospitalar": "Valor Total",
    "vl_total_base": "Valor Total Base",
    "valor_total_com_incrementos": "Valor c/ Incrementos",
    "valor_estimado": "Valor Estimado",
    "valores_base": "Valores Base",
    "valor_adicional": "Valor Adicional",
    "valor_a": "Valor em A",
    "valor_b": "Valor em B",
    # CID
    "co_cid": "CID",
    "no_cid": "Nome CID",
    "cid": "CID",
    "cid_nome": "Nome CID",
    "st_principal": "Diag. Principal",
    "total_cids_permitidos": "CIDs Permitidos",
    "sexo_paciente": "Sexo Paciente",
    "sexo_cid": "Sexo CID",
    # CNES
    "cnes": "CNES",
    # Competência
    "competencia": "Competência",
    "competencia_a": "Competência A",
    "competencia_b": "Competência B",
    "competencia_sigtap": "Competência SIGTAP",
    "competencia_cnes": "Competência CNES",
    # Validação / Auditoria
    "validacoes": "Validações",
    "alertas": "Alertas",
    "tipo": "Tipo",
    "procedimento": "Procedimento",
    "diferencas": "Diferenças",
    "campo": "Campo",
    # Quantidades
    "total": "Total",
    "quantidade": "Quantidade",
    "qt_idade_minima": "Idade Mínima",
    "qt_idade_maxima": "Idade Máxima",
    "qt_maxima_execucao": "Máx. Execuções",
    "qt_dias_permanencia": "Dias Permanência",
    "qt_pontos": "Pontos",
    "qt_tempo_permanencia": "Permanência Máx.",
    "idade_paciente": "Idade Paciente",
    "idade_minima": "Idade Mínima",
    "idade_maxima": "Idade Máxima",
    # Habilitação
    "co_habilitacao": "Cód. Habilitação",
    "no_habilitacao": "Habilitação",
    "habilitacoes": "Habilitações",
    # Serviços / Leitos / Ocupações
    "exigidos": "Exigidos",
    "exigidas": "Exigidas",
    "cnes_possui": "CNES Possui",
    "co_ocupacao": "CBO",
    "no_ocupacao": "Ocupação",
    "profissionais_no_cnes": "Profissionais no CNES",
    "autorizada_sigtap": "Autorizada SIGTAP",
    "co_secundario": "Cód. Secundário",
    # Incrementos
    "incrementos": "Incrementos",
    "pct_sh": "% SH",
    "pct_sa": "% SA",
    "pct_sp": "% SP",
    # Listas
    "procedimentos": "Procedimentos",
    "existe_a": "Existe em A",
    "existe_b": "Existe em B",
    "cids": "CIDs",
    "servicos": "Serviços",
    "leitos": "Leitos",
    "ocupacoes": "Ocupações",
    "compatibilidades": "Compatibilidades",
    "regras_condicionadas": "Regras Condicionadas",
    # Perfil
    "total_leitos_sus": "Total Leitos SUS",
    "tipos_leito": "Tipos de Leito",
    "total_servicos": "Total Serviços",
    "total_habilitacoes": "Total Habilitações",
    "total_profissionais": "Total Profissionais",
    "total_ocupacoes_distintas": "Ocupações Distintas",
    "top_ocupacoes": "Principais Ocupações",
    "codigos": "Códigos",
    "adicionados": "Adicionados",
    "removidos": "Removidos",
    "adicionadas": "Adicionadas",
    "removidas": "Removidas",
}


def _formatar(dados: Any, nivel: int = 0) -> str:
    """Formata dados estruturados como texto legível."""
    prefixo = "  " * nivel

    if isinstance(dados, dict):
        linhas: list[str] = []
        for chave, valor in dados.items():
            rotulo = _ROTULOS.get(chave, chave)

            if isinstance(valor, bool):
                linhas.append(f"{prefixo}{rotulo}: {'Sim' if valor else 'Não'}")
            elif valor is None:
                linhas.append(f"{prefixo}{rotulo}: -")
            elif isinstance(valor, dict):
                linhas.append(f"{prefixo}{rotulo}:")
                linhas.append(_formatar(valor, nivel + 1))
            elif isinstance(valor, list):
                if not valor:
                    linhas.append(f"{prefixo}{rotulo}: (nenhum)")
                elif all(isinstance(v, str) for v in valor):
                    linhas.append(f"{prefixo}{rotulo}:")
                    for item in valor:
                        linhas.append(f"{prefixo}  - {item}")
                elif all(isinstance(v, dict) for v in valor):
                    linhas.append(f"{prefixo}{rotulo} ({len(valor)}):")
                    for i, item in enumerate(valor, 1):
                        linhas.append(f"{prefixo}  [{i}]")
                        linhas.append(_formatar(item, nivel + 2))
                else:
                    linhas.append(f"{prefixo}{rotulo}:")
                    for item in valor:
                        linhas.append(f"{prefixo}  - {item}")
            else:
                linhas.append(f"{prefixo}{rotulo}: {valor}")
        return "\n".join(linhas)

    elif isinstance(dados, list):
        return _formatar({"resultados": dados}, nivel)

    return f"{prefixo}{dados}"


def _json(data: Any) -> str:
    """Formata dados como texto legível para consumo por LLM."""
    return _formatar(data)


def _erro(msg: str) -> str:
    return f"Erro: {msg}"


def _resolver_comp(client: Any, competencia: str, fonte: str = "SIGTAP") -> str:
    """Resolve competencia: usa a fornecida ou busca a mais recente."""
    if competencia:
        return competencia
    return client.ultima_competencia(fonte)


def _norm_proc(codigo: str) -> str:
    """Normaliza codigo de procedimento SIGTAP.

    O SIH usa 10 digitos com zero a esquerda (ex: 0407030034),
    mas o Parquet SIGTAP armazena 9 digitos (ex: 407030034).
    """
    codigo = codigo.strip()
    if len(codigo) == 10 and codigo.startswith("0"):
        return codigo[1:]
    return codigo
