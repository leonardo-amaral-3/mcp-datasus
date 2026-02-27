"""Tools MCP para auditoria cruzada SIGTAP x CNES."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from . import _erro, _json, _resolver_comp

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..datasus.client import DatasusClient


def register(mcp: "FastMCP", get_client: Callable[[], "DatasusClient"]) -> None:
    """Registra 3 tools de auditoria no servidor MCP."""

    @mcp.tool()
    def validar_procedimento_cnes(
        codigo_procedimento: str,
        codigo_cnes: str,
        competencia: str = "",
    ) -> str:
        """Valida se um CNES pode executar um procedimento SIGTAP.

        Cruza exigencias do procedimento (habilitacoes, servicos, leitos, ocupacoes)
        com o que o estabelecimento possui no CNES. Retorna um relatorio de
        conformidade com itens atendidos e pendencias.

        Essencial para auditoria preventiva de faturamento hospitalar.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            codigo_cnes: Codigo CNES (7 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp_s = _resolver_comp(c, competencia, "SIGTAP")
        comp_c = _resolver_comp(c, competencia, "CNES")

        proc = c.sigtap.procedimentos.get_by_id(codigo_procedimento, comp_s)
        if not proc:
            return _erro(f"Procedimento '{codigo_procedimento}' nao encontrado.")

        resultado = {
            "procedimento": {
                "codigo": codigo_procedimento,
                "nome": proc.get("no_procedimento", ""),
            },
            "cnes": codigo_cnes,
            "competencia_sigtap": comp_s,
            "competencia_cnes": comp_c,
            "validacoes": [],
            "conforme": True,
        }

        # 1. Habilitacoes exigidas vs CNES
        habs_exigidas = c.sigtap.rl_procedimento_habilitacao.list_by_ids(
            [codigo_procedimento], comp_s
        )
        habs_cnes_raw = c._conn.execute(
            "SELECT cod_sub_grupo_habilitacao FROM tb_habilitacao_cnes "
            "WHERE cnes = ? AND dt_competencia = ?",
            [codigo_cnes, comp_c],
        )
        habs_cnes = {h["cod_sub_grupo_habilitacao"] for h in habs_cnes_raw}

        if habs_exigidas:
            hab_codes = {h["co_habilitacao"] for h in habs_exigidas}
            # Verificar se pelo menos uma habilitacao exigida esta presente
            tem_hab = bool(hab_codes & habs_cnes)
            if not tem_hab:
                resultado["conforme"] = False
            resultado["validacoes"].append({
                "tipo": "habilitacao",
                "exigidas": list(hab_codes),
                "cnes_possui": list(habs_cnes),
                "atendido": tem_hab,
            })

        # 2. Servicos exigidos vs CNES
        servs_exigidos = c.sigtap.rl_procedimento_servico.list_by_ids(
            [codigo_procedimento], comp_s
        )
        servs_cnes = c.cnes.servicos.list_by_cnes(codigo_cnes, comp_c)
        servs_cnes_set = {(s["co_servico"], s.get("co_classificacao", "")) for s in servs_cnes}

        if servs_exigidos:
            servs_req = {(s["co_servico"], s.get("co_classificacao", "")) for s in servs_exigidos}
            tem_serv = bool(servs_req & servs_cnes_set)
            if not tem_serv:
                resultado["conforme"] = False
            resultado["validacoes"].append({
                "tipo": "servico",
                "exigidos": [{"servico": s, "class": cl} for s, cl in servs_req],
                "cnes_possui": [{"servico": s, "class": cl} for s, cl in servs_cnes_set],
                "atendido": tem_serv,
            })

        # 3. Leitos exigidos vs CNES
        leitos_exigidos = c.sigtap.rl_procedimento_leito.list_by_ids(
            [codigo_procedimento], comp_s
        )
        leitos_cnes = c.cnes.leitos.list_by_cnes(codigo_cnes, comp_c)
        leitos_cnes_set = {l["co_tipo_leito"] for l in leitos_cnes}

        if leitos_exigidos:
            leitos_req = {l["co_tipo_leito"] for l in leitos_exigidos}
            tem_leito = bool(leitos_req & leitos_cnes_set)
            if not tem_leito:
                resultado["conforme"] = False
            resultado["validacoes"].append({
                "tipo": "leito",
                "exigidos": list(leitos_req),
                "cnes_possui": list(leitos_cnes_set),
                "atendido": tem_leito,
            })

        # 4. Ocupacoes exigidas vs profissionais CNES
        ocups_exigidas = c.sigtap.rl_procedimento_ocupacao.list_by_ids(
            [codigo_procedimento], comp_s
        )
        profs_cnes = c.cnes.profissionais.list_by_cnes(codigo_cnes, comp_c)
        ocups_cnes = {p["co_ocupacao"] for p in profs_cnes}

        if ocups_exigidas:
            ocups_req = {o["co_ocupacao"] for o in ocups_exigidas}
            tem_prof = bool(ocups_req & ocups_cnes)
            if not tem_prof:
                resultado["conforme"] = False
            resultado["validacoes"].append({
                "tipo": "ocupacao_profissional",
                "exigidas": list(ocups_req),
                "cnes_possui": list(ocups_cnes & ocups_req),
                "atendido": tem_prof,
            })

        return _json(resultado)

    @mcp.tool()
    def validar_cid_procedimento(
        codigo_procedimento: str,
        codigo_cid: str,
        competencia: str = "",
    ) -> str:
        """Valida se um CID e permitido para um procedimento SIGTAP.

        Verifica a tabela rl_procedimento_cid e retorna se o CID pode ser
        usado como diagnostico principal ou secundario.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            codigo_cid: Codigo CID-10. Ex: 'I10', 'C50.9'.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia)

        proc = c.sigtap.procedimentos.get_by_id(codigo_procedimento, comp)
        if not proc:
            return _erro(f"Procedimento '{codigo_procedimento}' nao encontrado.")

        cids = c.sigtap.rl_procedimento_cid.list_by_ids([codigo_procedimento], comp)

        encontrado = None
        for rel in cids:
            if rel["co_cid"] == codigo_cid:
                encontrado = rel
                break

        if not encontrado:
            cid_info = c.sigtap.cid.get_by_id(codigo_cid, comp)
            return _json({
                "valido": False,
                "procedimento": proc.get("no_procedimento", ""),
                "cid": codigo_cid,
                "cid_nome": cid_info.get("no_cid", "") if cid_info else "CID nao encontrado",
                "msg": f"CID {codigo_cid} NAO e permitido para o procedimento {codigo_procedimento}.",
                "total_cids_permitidos": len(cids),
            })

        cid_info = c.sigtap.cid.get_by_id(codigo_cid, comp)
        return _json({
            "valido": True,
            "procedimento": proc.get("no_procedimento", ""),
            "cid": codigo_cid,
            "cid_nome": cid_info.get("no_cid", "") if cid_info else "",
            "st_principal": encontrado["st_principal"],
            "tp_sexo": cid_info.get("tp_sexo", "") if cid_info else "",
        })

    @mcp.tool()
    def perfil_auditoria(
        codigo_cnes: str, competencia: str = ""
    ) -> str:
        """Gera perfil completo de auditoria de um estabelecimento.

        Combina dados CNES (leitos, servicos, habilitacoes, profissionais)
        com resolucao de nomes via SIGTAP. Inclui resumo quantitativo
        para visao gerencial do estabelecimento.

        Args:
            codigo_cnes: Codigo CNES (7 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp_c = _resolver_comp(c, competencia, "CNES")
        comp_s = _resolver_comp(c, "", "SIGTAP")

        leitos = c.cnes.leitos.list_by_cnes(codigo_cnes, comp_c)
        servicos = c.cnes.servicos.list_by_cnes(codigo_cnes, comp_c)
        profs = c.cnes.profissionais.list_by_cnes(codigo_cnes, comp_c)
        habs = c._conn.execute(
            "SELECT * FROM tb_habilitacao_cnes WHERE cnes = ? AND dt_competencia = ?",
            [codigo_cnes, comp_c],
        )

        if not any([leitos, servicos, profs, habs]):
            return _erro(f"CNES '{codigo_cnes}' sem dados na competencia {comp_c}.")

        # Resolver nomes
        leito_codes = list({l["co_tipo_leito"] for l in leitos})
        leito_infos = c.sigtap.tipo_leito.list_by_ids(leito_codes, comp_s) if leito_codes else []
        leito_map = {l["co_tipo_leito"]: l["no_tipo_leito"] for l in leito_infos}

        ocup_count: dict[str, int] = {}
        for p in profs:
            ocup_count[p["co_ocupacao"]] = ocup_count.get(p["co_ocupacao"], 0) + 1
        ocup_codes = list(ocup_count.keys())
        ocup_infos = c.sigtap.ocupacao.list_by_ids(ocup_codes, comp_s) if ocup_codes else []
        ocup_map = {o["co_ocupacao"]: o["no_ocupacao"] for o in ocup_infos}

        total_leitos = sum(int(l.get("quantidade_sus", 0) or 0) for l in leitos)

        return _json({
            "cnes": codigo_cnes,
            "competencia": comp_c,
            "resumo": {
                "total_leitos_sus": total_leitos,
                "tipos_leito": len(leito_codes),
                "total_servicos": len(servicos),
                "total_habilitacoes": len(habs),
                "total_profissionais": len(profs),
                "total_ocupacoes_distintas": len(ocup_count),
            },
            "leitos": [
                {"tipo": leito_map.get(l["co_tipo_leito"], l["co_tipo_leito"]),
                 "quantidade_sus": l.get("quantidade_sus", 0)}
                for l in leitos
            ],
            "top_ocupacoes": sorted(
                [{"co_ocupacao": oc, "no_ocupacao": ocup_map.get(oc, ""), "quantidade": qt}
                 for oc, qt in ocup_count.items()],
                key=lambda x: x["quantidade"],
                reverse=True,
            )[:15],
            "habilitacoes": [h["cod_sub_grupo_habilitacao"] for h in habs],
        })
