"""Tools MCP de alto nivel para auditoria inteligente de AIH.

Combinam SIGTAP, CID, CNES e regras para validacao completa
de internacoes hospitalares e calculo de valores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from . import _erro, _json, _resolver_comp

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..datasus.client import DatasusClient


def register(mcp: "FastMCP", get_client: Callable[[], "DatasusClient"]) -> None:
    """Registra 2 tools de auditoria inteligente de AIH."""

    @mcp.tool()
    def auditar_aih(
        codigo_procedimento: str,
        codigo_cid: str,
        codigo_cnes: str,
        co_ocupacao_executante: str = "",
        sexo_paciente: str = "",
        idade_paciente: int = -1,
        dias_permanencia: int = -1,
        procedimentos_secundarios: str = "",
        competencia: str = "",
    ) -> str:
        """Auditoria completa de uma AIH cruzando SIGTAP, CID, CNES e regras.

        Valida todos os aspectos de uma internacao hospitalar:
        - Procedimento existe e e valido
        - CID e permitido para o procedimento
        - Restricao de sexo no CID vs paciente
        - Idade do paciente dentro da faixa permitida
        - CNES tem habilitacoes, servicos, leitos e profissionais exigidos
        - Procedimentos secundarios sao compativeis
        - Calcula valor estimado da AIH

        Retorna relatorio de conformidade com alertas e pendencias.

        Args:
            codigo_procedimento: Codigo do procedimento principal (10 digitos).
            codigo_cid: Codigo CID-10 do diagnostico principal. Ex: 'I10'.
            codigo_cnes: Codigo CNES do hospital (7 digitos).
            co_ocupacao_executante: Codigo CBO do profissional executante.
            sexo_paciente: Sexo do paciente ('M' ou 'F').
            idade_paciente: Idade do paciente em anos (-1 = nao informado).
            dias_permanencia: Dias de permanencia (-1 = nao informado).
            procedimentos_secundarios: Codigos separados por virgula. Ex: '0301010072,0415020018'.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        client = get_client()
        comp_s = _resolver_comp(client, competencia, "SIGTAP")
        comp_c = _resolver_comp(client, competencia, "CNES")

        alertas: list[str] = []
        validacoes: list[dict] = []

        # 1. Procedimento existe?
        proc = client.sigtap.procedimentos.get_by_id(codigo_procedimento, comp_s)
        if not proc:
            return _json({
                "conforme": False,
                "erro": f"Procedimento '{codigo_procedimento}' nao encontrado.",
                "validacoes": [],
                "alertas": [
                    f"Procedimento {codigo_procedimento} inexistente na competencia {comp_s}."
                ],
            })

        # 2. CID permitido?
        cids_rel = client.sigtap.rl_procedimento_cid.list_by_ids(
            [codigo_procedimento], comp_s
        )
        cid_encontrado = next(
            (r for r in cids_rel if r["co_cid"] == codigo_cid), None
        )
        cid_info = client.sigtap.cid.get_by_id(codigo_cid, comp_s)

        cid_valido = cid_encontrado is not None
        if not cid_valido:
            alertas.append(
                f"CID {codigo_cid} NAO e permitido para o procedimento "
                f"{codigo_procedimento}."
            )
        validacoes.append({
            "tipo": "cid",
            "atendido": cid_valido,
            "co_cid": codigo_cid,
            "no_cid": cid_info.get("no_cid", "") if cid_info else "CID nao encontrado",
            "st_principal": cid_encontrado["st_principal"] if cid_encontrado else "",
            "total_cids_permitidos": len(cids_rel),
        })

        # 3. Restricao de sexo
        if sexo_paciente and cid_info:
            tp_sexo = cid_info.get("tp_sexo", "")
            sexo_ok = tp_sexo in ("", "I") or tp_sexo == sexo_paciente
            if not sexo_ok:
                alertas.append(
                    f"CID {codigo_cid} restrito ao sexo '{tp_sexo}', "
                    f"paciente e '{sexo_paciente}'."
                )
            validacoes.append({
                "tipo": "sexo",
                "atendido": sexo_ok,
                "sexo_paciente": sexo_paciente,
                "sexo_cid": tp_sexo,
            })

        # 4. Faixa etaria
        if idade_paciente >= 0:
            idade_min = int(proc.get("qt_idade_minima", 0) or 0)
            idade_max = int(proc.get("qt_idade_maxima", 999) or 999)
            idade_ok = idade_min <= idade_paciente <= idade_max
            if not idade_ok:
                alertas.append(
                    f"Idade {idade_paciente} fora da faixa permitida "
                    f"({idade_min}-{idade_max})."
                )
            validacoes.append({
                "tipo": "idade",
                "atendido": idade_ok,
                "idade_paciente": idade_paciente,
                "idade_minima": idade_min,
                "idade_maxima": idade_max,
            })

        # 5. Habilitacoes CNES
        habs_exigidas = client.sigtap.rl_procedimento_habilitacao.list_by_ids(
            [codigo_procedimento], comp_s
        )
        if habs_exigidas:
            habs_cnes_raw = client._conn.execute(
                "SELECT cod_sub_grupo_habilitacao FROM tb_habilitacao_cnes "
                "WHERE cnes = ? AND dt_competencia = ?",
                [codigo_cnes, comp_c],
            )
            habs_cnes = {h["cod_sub_grupo_habilitacao"] for h in habs_cnes_raw}
            hab_codes = {h["co_habilitacao"] for h in habs_exigidas}
            tem_hab = bool(hab_codes & habs_cnes)
            if not tem_hab:
                alertas.append(
                    f"CNES {codigo_cnes} sem habilitacoes exigidas: "
                    f"{list(hab_codes)}."
                )
            validacoes.append({
                "tipo": "habilitacao",
                "atendido": tem_hab,
                "exigidas": list(hab_codes),
                "cnes_possui": list(habs_cnes & hab_codes),
            })

        # 6. Servicos CNES
        servs_exigidos = client.sigtap.rl_procedimento_servico.list_by_ids(
            [codigo_procedimento], comp_s
        )
        if servs_exigidos:
            servs_cnes = client.cnes.servicos.list_by_cnes(codigo_cnes, comp_c)
            servs_cnes_set = {
                (s["co_servico"], s.get("co_classificacao", "")) for s in servs_cnes
            }
            servs_req = {
                (s["co_servico"], s.get("co_classificacao", "")) for s in servs_exigidos
            }
            tem_serv = bool(servs_req & servs_cnes_set)
            if not tem_serv:
                alertas.append(f"CNES {codigo_cnes} sem servicos exigidos.")
            validacoes.append({
                "tipo": "servico",
                "atendido": tem_serv,
                "exigidos": [{"servico": s, "class": cl} for s, cl in servs_req],
            })

        # 7. Leitos CNES
        leitos_exigidos = client.sigtap.rl_procedimento_leito.list_by_ids(
            [codigo_procedimento], comp_s
        )
        if leitos_exigidos:
            leitos_cnes = client.cnes.leitos.list_by_cnes(codigo_cnes, comp_c)
            leitos_cnes_set = {lt["co_tipo_leito"] for lt in leitos_cnes}
            leitos_req = {lt["co_tipo_leito"] for lt in leitos_exigidos}
            tem_leito = bool(leitos_req & leitos_cnes_set)
            if not tem_leito:
                alertas.append(
                    f"CNES {codigo_cnes} sem tipos de leito exigidos: "
                    f"{list(leitos_req)}."
                )
            validacoes.append({
                "tipo": "leito",
                "atendido": tem_leito,
                "exigidos": list(leitos_req),
                "cnes_possui": list(leitos_cnes_set & leitos_req),
            })

        # 8. Ocupacao do executante
        if co_ocupacao_executante:
            ocups_exigidas = client.sigtap.rl_procedimento_ocupacao.list_by_ids(
                [codigo_procedimento], comp_s
            )
            ocups_req = {o["co_ocupacao"] for o in ocups_exigidas}
            ocup_ok = not ocups_req or co_ocupacao_executante in ocups_req
            if not ocup_ok:
                alertas.append(
                    f"CBO {co_ocupacao_executante} nao autorizado. "
                    f"Permitidos: {list(ocups_req)}."
                )
            profs_cnes = client.cnes.profissionais.list_by_cnes_e_ocupacao(
                codigo_cnes, co_ocupacao_executante, comp_c
            )
            validacoes.append({
                "tipo": "ocupacao_executante",
                "atendido": ocup_ok,
                "co_ocupacao": co_ocupacao_executante,
                "autorizada_sigtap": (
                    co_ocupacao_executante in ocups_req if ocups_req else True
                ),
                "profissionais_no_cnes": len(profs_cnes),
            })

        # 9. Procedimentos secundarios compativeis
        if procedimentos_secundarios:
            sec_codes = [
                s.strip()
                for s in procedimentos_secundarios.split(",")
                if s.strip()
            ]
            compat = client.sigtap.rl_procedimento_compativel.list_by_procedimentos(
                [codigo_procedimento], comp_s
            )
            compat_set = {r["co_procedimento_compativel"] for r in compat}
            for sec in sec_codes:
                sec_ok = sec in compat_set
                if not sec_ok:
                    alertas.append(
                        f"Secundario {sec} incompativel com "
                        f"{codigo_procedimento}."
                    )
                validacoes.append({
                    "tipo": "compatibilidade_secundario",
                    "atendido": sec_ok,
                    "co_secundario": sec,
                })

        # 10. Valor estimado
        valor_sh = float(proc.get("vl_sh", 0) or 0)
        valor_sa = float(proc.get("vl_sa", 0) or 0)
        valor_sp = float(proc.get("vl_sp", 0) or 0)
        valor_total = round(valor_sh + valor_sa + valor_sp, 2)

        conforme = all(v["atendido"] for v in validacoes)

        return _json({
            "conforme": conforme,
            "procedimento": {
                "codigo": codigo_procedimento,
                "nome": proc.get("no_procedimento", ""),
            },
            "cnes": codigo_cnes,
            "competencia_sigtap": comp_s,
            "competencia_cnes": comp_c,
            "validacoes": validacoes,
            "alertas": alertas,
            "valor_estimado": {
                "vl_sh": valor_sh,
                "vl_sa": valor_sa,
                "vl_sp": valor_sp,
                "vl_total": valor_total,
            },
        })

    @mcp.tool()
    def calcular_valor_aih(
        codigo_procedimento: str,
        codigo_cnes: str = "",
        competencia: str = "",
    ) -> str:
        """Calcula o valor estimado de uma AIH com incrementos por habilitacao.

        Retorna valores base (SH, SA, SP) e incrementos financeiros
        aplicaveis com base nas habilitacoes do CNES informado.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            codigo_cnes: Codigo CNES (7 digitos) para calcular incrementos. Opcional.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        client = get_client()
        comp_s = _resolver_comp(client, competencia, "SIGTAP")

        proc = client.sigtap.procedimentos.get_by_id(codigo_procedimento, comp_s)
        if not proc:
            return _erro(f"Procedimento '{codigo_procedimento}' nao encontrado.")

        valor_sh = float(proc.get("vl_sh", 0) or 0)
        valor_sa = float(proc.get("vl_sa", 0) or 0)
        valor_sp = float(proc.get("vl_sp", 0) or 0)
        valor_base = round(valor_sh + valor_sa + valor_sp, 2)

        resultado = {
            "procedimento": {
                "codigo": codigo_procedimento,
                "nome": proc.get("no_procedimento", ""),
            },
            "competencia": comp_s,
            "valores_base": {
                "vl_sh": valor_sh,
                "vl_sa": valor_sa,
                "vl_sp": valor_sp,
                "vl_total_base": valor_base,
            },
            "incrementos": [],
            "valor_total_com_incrementos": valor_base,
        }

        if not codigo_cnes:
            return _json(resultado)

        comp_c = _resolver_comp(client, competencia, "CNES")
        incrs = client.sigtap.rl_procedimento_incremento.list_by_ids(
            [codigo_procedimento], comp_s
        )

        if not incrs:
            return _json(resultado)

        habs_cnes_raw = client._conn.execute(
            "SELECT cod_sub_grupo_habilitacao FROM tb_habilitacao_cnes "
            "WHERE cnes = ? AND dt_competencia = ?",
            [codigo_cnes, comp_c],
        )
        habs_cnes = {h["cod_sub_grupo_habilitacao"] for h in habs_cnes_raw}

        hab_codes = list({i["co_habilitacao"] for i in incrs})
        hab_infos = client.sigtap.habilitacao.list_by_ids(hab_codes, comp_s)
        hab_map = {h["co_habilitacao"]: h["no_habilitacao"] for h in hab_infos}

        incr_total_sh = 0.0
        incr_total_sa = 0.0
        incr_total_sp = 0.0

        for incr in incrs:
            hab_code = incr["co_habilitacao"]
            aplicavel = hab_code in habs_cnes
            pct_sh = float(incr.get("vl_percentual_sh", 0) or 0)
            pct_sa = float(incr.get("vl_percentual_sa", 0) or 0)
            pct_sp = float(incr.get("vl_percentual_sp", 0) or 0)

            add_sh = valor_sh * pct_sh / 100 if aplicavel else 0
            add_sa = valor_sa * pct_sa / 100 if aplicavel else 0
            add_sp = valor_sp * pct_sp / 100 if aplicavel else 0

            if aplicavel:
                incr_total_sh += add_sh
                incr_total_sa += add_sa
                incr_total_sp += add_sp

            resultado["incrementos"].append({
                "co_habilitacao": hab_code,
                "no_habilitacao": hab_map.get(hab_code, ""),
                "aplicavel": aplicavel,
                "pct_sh": pct_sh,
                "pct_sa": pct_sa,
                "pct_sp": pct_sp,
                "valor_adicional": round(add_sh + add_sa + add_sp, 2),
            })

        resultado["valor_total_com_incrementos"] = round(
            valor_base + incr_total_sh + incr_total_sa + incr_total_sp, 2
        )

        return _json(resultado)
