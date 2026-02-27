"""Tools MCP para consulta completa ao CNES (5 tabelas)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from . import _erro, _json, _resolver_comp

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..datasus.client import DatasusClient


def register(mcp: "FastMCP", get_client: Callable[[], "DatasusClient"]) -> None:
    """Registra 6 tools CNES no servidor MCP."""

    @mcp.tool()
    def consultar_cnes_completo(
        codigo_cnes: str, competencia: str = ""
    ) -> str:
        """Consulta perfil completo de um estabelecimento CNES.

        Retorna leitos (com nomes dos tipos), servicos (com nomes e classificacoes),
        habilitacoes (com nomes do grupo), profissionais agrupados por ocupacao
        (com nomes CBO). Tudo com resolucao de nomes via SIGTAP.

        Args:
            codigo_cnes: Codigo CNES (7 digitos). Ex: '2077485'.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia, "CNES")

        leitos = c.cnes.leitos.list_by_cnes(codigo_cnes, comp)
        servicos = c.cnes.servicos.list_by_cnes(codigo_cnes, comp)
        profs = c.cnes.profissionais.list_by_cnes(codigo_cnes, comp)

        # Habilitacoes - buscar por CNES via query direta
        habs_raw = c._conn.execute(
            "SELECT * FROM tb_habilitacao_cnes WHERE cnes = ? AND dt_competencia = ?",
            [codigo_cnes, comp],
        )

        # Resolver nomes de tipo de leito (via SIGTAP)
        comp_sigtap = _resolver_comp(c, "", "SIGTAP")
        leito_codes = list({l["co_tipo_leito"] for l in leitos})
        leito_infos = c.sigtap.tipo_leito.list_by_ids(leito_codes, comp_sigtap) if leito_codes else []
        leito_map = {l["co_tipo_leito"]: l["no_tipo_leito"] for l in leito_infos}

        # Resolver nomes de servico (via SIGTAP)
        serv_codes = list({s["co_servico"] for s in servicos})
        serv_infos = c.sigtap.servico.list_by_ids(serv_codes, comp_sigtap) if serv_codes else []
        serv_map = {s["co_servico"]: s["no_servico"] for s in serv_infos}

        # Resolver classificacoes
        class_infos = c.sigtap.servico_classificacao.list_all(comp_sigtap)
        class_map = {(cl["co_servico"], cl["co_classificacao"]): cl["no_classificacao"] for cl in class_infos}

        # Resolver nomes de ocupacao (via SIGTAP)
        ocup_codes = list({p["co_ocupacao"] for p in profs})
        ocup_infos = c.sigtap.ocupacao.list_by_ids(ocup_codes, comp_sigtap) if ocup_codes else []
        ocup_map = {o["co_ocupacao"]: o["no_ocupacao"] for o in ocup_infos}

        # Resolver nomes de habilitacao (via SIGTAP)
        hab_codes = [h["cod_sub_grupo_habilitacao"] for h in habs_raw]
        ghab_infos = c.sigtap.grupo_habilitacao.list_all(comp_sigtap)
        ghab_map = {g["nu_grupo_habilitacao"]: g["no_grupo_habilitacao"] for g in ghab_infos}

        # Agrupar profissionais por ocupacao
        ocup_count: dict[str, int] = {}
        for p in profs:
            oc = p["co_ocupacao"]
            ocup_count[oc] = ocup_count.get(oc, 0) + 1

        return _json({
            "cnes": codigo_cnes,
            "competencia": comp,
            "leitos": [
                {**l, "no_tipo_leito": leito_map.get(l["co_tipo_leito"], "")}
                for l in leitos
            ],
            "total_leitos_sus": sum(int(l.get("quantidade_sus", 0) or 0) for l in leitos),
            "servicos": [
                {**s, "no_servico": serv_map.get(s["co_servico"], ""),
                 "no_classificacao": class_map.get((s["co_servico"], s.get("co_classificacao", "")), "")}
                for s in servicos
            ],
            "habilitacoes": [
                {"cod_sub_grupo": h["cod_sub_grupo_habilitacao"],
                 "no_grupo": ghab_map.get(h["cod_sub_grupo_habilitacao"], "")}
                for h in habs_raw
            ],
            "profissionais_por_ocupacao": [
                {"co_ocupacao": oc, "no_ocupacao": ocup_map.get(oc, ""), "quantidade": qt}
                for oc, qt in sorted(ocup_count.items())
            ],
            "total_profissionais": len(profs),
        })

    @mcp.tool()
    def consultar_leitos_cnes_detalhado(
        codigo_cnes: str, competencia: str = ""
    ) -> str:
        """Lista leitos de um CNES com nomes dos tipos de leito resolvidos.

        Args:
            codigo_cnes: Codigo CNES (7 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia, "CNES")
        leitos = c.cnes.leitos.list_by_cnes(codigo_cnes, comp)
        if not leitos:
            return _json({"cnes": codigo_cnes, "leitos": [], "msg": "Nenhum leito encontrado."})

        comp_s = _resolver_comp(c, "", "SIGTAP")
        leito_codes = list({l["co_tipo_leito"] for l in leitos})
        leito_infos = c.sigtap.tipo_leito.list_by_ids(leito_codes, comp_s)
        leito_map = {l["co_tipo_leito"]: l["no_tipo_leito"] for l in leito_infos}

        return _json({
            "cnes": codigo_cnes,
            "competencia": comp,
            "total_sus": sum(int(l.get("quantidade_sus", 0) or 0) for l in leitos),
            "leitos": [{**l, "no_tipo_leito": leito_map.get(l["co_tipo_leito"], "")} for l in leitos],
        })

    @mcp.tool()
    def consultar_servicos_cnes_detalhado(
        codigo_cnes: str, competencia: str = ""
    ) -> str:
        """Lista servicos de um CNES com nomes e classificacoes resolvidos.

        Args:
            codigo_cnes: Codigo CNES (7 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia, "CNES")
        servicos = c.cnes.servicos.list_by_cnes(codigo_cnes, comp)
        if not servicos:
            return _json({"cnes": codigo_cnes, "servicos": [], "msg": "Nenhum servico encontrado."})

        comp_s = _resolver_comp(c, "", "SIGTAP")
        serv_codes = list({s["co_servico"] for s in servicos})
        serv_infos = c.sigtap.servico.list_by_ids(serv_codes, comp_s)
        serv_map = {s["co_servico"]: s["no_servico"] for s in serv_infos}

        class_infos = c.sigtap.servico_classificacao.list_all(comp_s)
        class_map = {(cl["co_servico"], cl["co_classificacao"]): cl["no_classificacao"] for cl in class_infos}

        return _json({
            "cnes": codigo_cnes,
            "competencia": comp,
            "servicos": [
                {**s, "no_servico": serv_map.get(s["co_servico"], ""),
                 "no_classificacao": class_map.get((s["co_servico"], s.get("co_classificacao", "")), "")}
                for s in servicos
            ],
        })

    @mcp.tool()
    def consultar_habilitacoes_cnes_detalhado(
        codigo_cnes: str, competencia: str = ""
    ) -> str:
        """Lista habilitacoes de um CNES com nomes resolvidos.

        Args:
            codigo_cnes: Codigo CNES (7 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia, "CNES")
        habs = c._conn.execute(
            "SELECT * FROM tb_habilitacao_cnes WHERE cnes = ? AND dt_competencia = ?",
            [codigo_cnes, comp],
        )
        if not habs:
            return _json({"cnes": codigo_cnes, "habilitacoes": [], "msg": "Nenhuma habilitacao."})

        comp_s = _resolver_comp(c, "", "SIGTAP")
        ghab_infos = c.sigtap.grupo_habilitacao.list_all(comp_s)
        ghab_map = {g["nu_grupo_habilitacao"]: g for g in ghab_infos}

        return _json({
            "cnes": codigo_cnes,
            "competencia": comp,
            "habilitacoes": [
                {"cod_sub_grupo": h["cod_sub_grupo_habilitacao"],
                 "no_grupo": ghab_map.get(h["cod_sub_grupo_habilitacao"], {}).get("no_grupo_habilitacao", ""),
                 "ds_grupo": ghab_map.get(h["cod_sub_grupo_habilitacao"], {}).get("ds_grupo_habilitacao", "")}
                for h in habs
            ],
        })

    @mcp.tool()
    def buscar_profissionais_detalhado(
        codigo_cnes: str, ocupacao: str = "", competencia: str = ""
    ) -> str:
        """Lista profissionais de um CNES com nomes de ocupacao resolvidos.

        Retorna identificador SUS, CBO, vinculacao e carga horaria.

        Args:
            codigo_cnes: Codigo CNES (7 digitos).
            ocupacao: Filtro por codigo CBO. Ex: '225142' (medico cirurgiao).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia, "CNES")

        if ocupacao:
            profs = c.cnes.profissionais.list_by_cnes_e_ocupacao(codigo_cnes, ocupacao, comp)
        else:
            profs = c.cnes.profissionais.list_by_cnes(codigo_cnes, comp)

        if not profs:
            return _json({"cnes": codigo_cnes, "profissionais": [], "msg": "Nenhum profissional."})

        comp_s = _resolver_comp(c, "", "SIGTAP")
        ocup_codes = list({p["co_ocupacao"] for p in profs})
        ocup_infos = c.sigtap.ocupacao.list_by_ids(ocup_codes, comp_s)
        ocup_map = {o["co_ocupacao"]: o["no_ocupacao"] for o in ocup_infos}

        return _json({
            "cnes": codigo_cnes,
            "competencia": comp,
            "total": len(profs),
            "profissionais": [
                {**p, "no_ocupacao": ocup_map.get(p["co_ocupacao"], "")}
                for p in profs
            ],
        })

    @mcp.tool()
    def consultar_dados_profissional(
        co_profissional_sus: str, competencia: str = ""
    ) -> str:
        """Consulta dados pessoais de um profissional (CPF, CNS).

        Retorna os estabelecimentos onde o profissional esta vinculado
        e seus dados de identificacao.

        Args:
            co_profissional_sus: Codigo do profissional no SUS.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia, "CNES")
        dados = c.cnes.dados_profissionais.get_by_id(co_profissional_sus, comp)
        if not dados:
            return _erro(f"Profissional '{co_profissional_sus}' nao encontrado.")
        return _json(dados)
