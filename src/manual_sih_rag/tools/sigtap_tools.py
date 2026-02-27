"""Tools MCP para consulta completa ao SIGTAP (41 tabelas)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from . import _erro, _json, _norm_proc, _resolver_comp

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..datasus.client import DatasusClient


def register(mcp: "FastMCP", get_client: Callable[[], "DatasusClient"]) -> None:
    """Registra 12 tools SIGTAP no servidor MCP."""

    @mcp.tool()
    def consultar_procedimento_completo(
        codigo: str, competencia: str = ""
    ) -> str:
        """Consulta procedimento SIGTAP com TODOS os dados relacionados.

        Retorna valores, CIDs permitidos, habilitacoes exigidas, servicos,
        ocupacoes (CBO), tipos de leito, incrementos e descricao completa.
        Use quando precisar do perfil completo de um procedimento para auditoria.

        Args:
            codigo: Codigo do procedimento (10 digitos). Ex: '0301010072'.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo = _norm_proc(codigo)
        c = get_client()
        comp = _resolver_comp(c, competencia)

        proc = c.sigtap.procedimentos.get_by_id(codigo, comp)
        if not proc:
            return _erro(f"Procedimento '{codigo}' nao encontrado.")

        # Relacionamentos
        cids_rel = c.sigtap.rl_procedimento_cid.list_by_ids([codigo], comp)
        habs_rel = c.sigtap.rl_procedimento_habilitacao.list_by_ids([codigo], comp)
        servs_rel = c.sigtap.rl_procedimento_servico.list_by_ids([codigo], comp)
        ocups_rel = c.sigtap.rl_procedimento_ocupacao.list_by_ids([codigo], comp)
        leitos_rel = c.sigtap.rl_procedimento_leito.list_by_ids([codigo], comp)
        incrs_rel = c.sigtap.rl_procedimento_incremento.list_by_ids([codigo], comp)
        descr = c.sigtap.descricao.get_by_id(codigo, comp)

        # Resolver nomes em lote
        cid_codes = [r["co_cid"] for r in cids_rel]
        cid_infos = c.sigtap.cid.list_by_ids(cid_codes, comp) if cid_codes else []
        cid_map = {ci["co_cid"]: ci["no_cid"] for ci in cid_infos}

        hab_codes = [r["co_habilitacao"] for r in habs_rel]
        hab_infos = c.sigtap.habilitacao.list_by_ids(hab_codes, comp) if hab_codes else []
        hab_map = {h["co_habilitacao"]: h["no_habilitacao"] for h in hab_infos}

        serv_codes = list({r["co_servico"] for r in servs_rel})
        serv_infos = c.sigtap.servico.list_by_ids(serv_codes, comp) if serv_codes else []
        serv_map = {s["co_servico"]: s["no_servico"] for s in serv_infos}

        ocup_codes = [r["co_ocupacao"] for r in ocups_rel]
        ocup_infos = c.sigtap.ocupacao.list_by_ids(ocup_codes, comp) if ocup_codes else []
        ocup_map = {o["co_ocupacao"]: o["no_ocupacao"] for o in ocup_infos}

        leito_codes = [r["co_tipo_leito"] for r in leitos_rel]
        leito_infos = c.sigtap.tipo_leito.list_by_ids(leito_codes, comp) if leito_codes else []
        leito_map = {l["co_tipo_leito"]: l["no_tipo_leito"] for l in leito_infos}

        return _json({
            "procedimento": proc,
            "descricao": descr.get("ds_procedimento", "") if descr else "",
            "competencia": comp,
            "cids": [
                {"co_cid": r["co_cid"], "no_cid": cid_map.get(r["co_cid"], ""), "st_principal": r["st_principal"]}
                for r in cids_rel
            ],
            "habilitacoes": [
                {"co_habilitacao": r["co_habilitacao"], "no_habilitacao": hab_map.get(r["co_habilitacao"], ""),
                 "nu_grupo": r.get("nu_grupo_habilitacao", "")}
                for r in habs_rel
            ],
            "servicos": [
                {"co_servico": r["co_servico"], "no_servico": serv_map.get(r["co_servico"], ""),
                 "co_classificacao": r.get("co_classificacao", "")}
                for r in servs_rel
            ],
            "ocupacoes": [
                {"co_ocupacao": r["co_ocupacao"], "no_ocupacao": ocup_map.get(r["co_ocupacao"], "")}
                for r in ocups_rel
            ],
            "leitos": [
                {"co_tipo_leito": r["co_tipo_leito"], "no_tipo_leito": leito_map.get(r["co_tipo_leito"], "")}
                for r in leitos_rel
            ],
            "incrementos": [
                {"co_habilitacao": r["co_habilitacao"], "no_habilitacao": hab_map.get(r["co_habilitacao"], ""),
                 "pct_sh": r.get("vl_percentual_sh"), "pct_sa": r.get("vl_percentual_sa"),
                 "pct_sp": r.get("vl_percentual_sp")}
                for r in incrs_rel
            ],
        })

    @mcp.tool()
    def buscar_cid(nome: str, competencia: str = "", limite: int = 30) -> str:
        """Busca codigos CID-10 por nome/descricao.

        Retorna codigos, nomes, tipo de agravo, sexo e estadio.
        Util para encontrar o CID correto para validacao de AIH.

        Args:
            nome: Termo de busca. Ex: 'diabetes', 'fratura femur', 'neoplasia'.
            competencia: Competencia AAAAMM. Default: mais recente.
            limite: Maximo de resultados. Default: 30.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia)
        resultados = c.sigtap.cid.search("no_cid", nome, comp, min(limite, 100))
        return _json(resultados)

    @mcp.tool()
    def consultar_cid(codigo: str, competencia: str = "") -> str:
        """Consulta um CID-10 pelo codigo.

        Retorna nome, tipo de agravo, restricao de sexo, estadio e campos irradiados.

        Args:
            codigo: Codigo CID-10. Ex: 'I10', 'C50', 'S72.0'.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia)
        cid = c.sigtap.cid.get_by_id(codigo, comp)
        if not cid:
            return _erro(f"CID '{codigo}' nao encontrado.")
        return _json(cid)

    @mcp.tool()
    def listar_cids_procedimento(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista todos os CIDs permitidos para um procedimento.

        Retorna codigos CID com indicacao se pode ser principal ou secundario.
        Essencial para validar se o CID da AIH e compativel com o procedimento.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_cid.list_by_ids([codigo_procedimento], comp)
        if not rels:
            return _json({"procedimento": codigo_procedimento, "cids": [], "msg": "Nenhum CID vinculado."})

        cid_codes = [r["co_cid"] for r in rels]
        cid_infos = c.sigtap.cid.list_by_ids(cid_codes, comp)
        cid_map = {ci["co_cid"]: ci for ci in cid_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "total": len(rels),
            "cids": [
                {"co_cid": r["co_cid"], "no_cid": cid_map.get(r["co_cid"], {}).get("no_cid", ""),
                 "st_principal": r["st_principal"],
                 "tp_sexo": cid_map.get(r["co_cid"], {}).get("tp_sexo", "")}
                for r in rels
            ],
        })

    @mcp.tool()
    def listar_compatibilidades(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista procedimentos compativeis com o procedimento informado.

        Mostra quais procedimentos podem ser cobrados juntos e as quantidades permitidas.
        Essencial para auditoria de contas com multiplos procedimentos.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        compat = c.sigtap.rl_procedimento_compativel.list_by_procedimentos(
            [codigo_procedimento], comp
        )
        # Resolver nomes
        all_codes = list({r["co_procedimento_principal"] for r in compat}
                        | {r["co_procedimento_compativel"] for r in compat})
        procs = c.sigtap.procedimentos.list_by_ids(all_codes, comp)
        nome_map = {p["co_procedimento"]: p["no_procedimento"] for p in procs}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "total": len(compat),
            "compatibilidades": [
                {"co_principal": r["co_procedimento_principal"],
                 "no_principal": nome_map.get(r["co_procedimento_principal"], ""),
                 "co_compativel": r["co_procedimento_compativel"],
                 "no_compativel": nome_map.get(r["co_procedimento_compativel"], ""),
                 "tp_compatibilidade": r["tp_compatibilidade"],
                 "qt_permitida": r.get("qt_permitida", "")}
                for r in compat
            ],
        })

    @mcp.tool()
    def consultar_habilitacoes_procedimento(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista habilitacoes exigidas para realizar um procedimento.

        Retorna codigos e nomes das habilitacoes que o estabelecimento deve ter.
        Fundamental para verificar se o hospital pode cobrar o procedimento.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_habilitacao.list_by_ids([codigo_procedimento], comp)

        hab_codes = [r["co_habilitacao"] for r in rels]
        hab_infos = c.sigtap.habilitacao.list_by_ids(hab_codes, comp) if hab_codes else []
        hab_map = {h["co_habilitacao"]: h["no_habilitacao"] for h in hab_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "habilitacoes": [
                {"co_habilitacao": r["co_habilitacao"],
                 "no_habilitacao": hab_map.get(r["co_habilitacao"], ""),
                 "nu_grupo_habilitacao": r.get("nu_grupo_habilitacao", "")}
                for r in rels
            ],
        })

    @mcp.tool()
    def consultar_servicos_procedimento(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista servicos/classificacoes exigidos para um procedimento.

        Retorna os servicos que o estabelecimento deve oferecer no CNES.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_servico.list_by_ids([codigo_procedimento], comp)

        serv_codes = list({r["co_servico"] for r in rels})
        serv_infos = c.sigtap.servico.list_by_ids(serv_codes, comp) if serv_codes else []
        serv_map = {s["co_servico"]: s["no_servico"] for s in serv_infos}

        class_codes = [(r["co_servico"], r.get("co_classificacao", "")) for r in rels]
        class_infos = c.sigtap.servico_classificacao.list_all(comp)
        class_map = {(cl["co_servico"], cl["co_classificacao"]): cl["no_classificacao"] for cl in class_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "servicos": [
                {"co_servico": r["co_servico"],
                 "no_servico": serv_map.get(r["co_servico"], ""),
                 "co_classificacao": r.get("co_classificacao", ""),
                 "no_classificacao": class_map.get((r["co_servico"], r.get("co_classificacao", "")), "")}
                for r in rels
            ],
        })

    @mcp.tool()
    def consultar_ocupacoes_procedimento(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista ocupacoes (CBO) autorizadas a executar um procedimento.

        Retorna os codigos CBO dos profissionais que podem realizar o procedimento.
        Use para verificar se o profissional da AIH tem o CBO correto.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_ocupacao.list_by_ids([codigo_procedimento], comp)

        ocup_codes = [r["co_ocupacao"] for r in rels]
        ocup_infos = c.sigtap.ocupacao.list_by_ids(ocup_codes, comp) if ocup_codes else []
        ocup_map = {o["co_ocupacao"]: o["no_ocupacao"] for o in ocup_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "ocupacoes": [
                {"co_ocupacao": r["co_ocupacao"], "no_ocupacao": ocup_map.get(r["co_ocupacao"], "")}
                for r in rels
            ],
        })

    @mcp.tool()
    def consultar_leitos_procedimento(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista tipos de leito exigidos para um procedimento.

        Retorna os tipos de leito que o estabelecimento deve dispor.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_leito.list_by_ids([codigo_procedimento], comp)

        leito_codes = [r["co_tipo_leito"] for r in rels]
        leito_infos = c.sigtap.tipo_leito.list_by_ids(leito_codes, comp) if leito_codes else []
        leito_map = {l["co_tipo_leito"]: l["no_tipo_leito"] for l in leito_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "leitos": [
                {"co_tipo_leito": r["co_tipo_leito"], "no_tipo_leito": leito_map.get(r["co_tipo_leito"], "")}
                for r in rels
            ],
        })

    @mcp.tool()
    def consultar_incrementos(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista incrementos financeiros de um procedimento por habilitacao.

        Mostra percentuais adicionais de SH, SA e SP por habilitacao.
        Importante para calcular o valor correto da AIH.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_incremento.list_by_ids([codigo_procedimento], comp)

        hab_codes = list({r["co_habilitacao"] for r in rels})
        hab_infos = c.sigtap.habilitacao.list_by_ids(hab_codes, comp) if hab_codes else []
        hab_map = {h["co_habilitacao"]: h["no_habilitacao"] for h in hab_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "incrementos": [
                {"co_habilitacao": r["co_habilitacao"],
                 "no_habilitacao": hab_map.get(r["co_habilitacao"], ""),
                 "vl_percentual_sh": r.get("vl_percentual_sh", ""),
                 "vl_percentual_sa": r.get("vl_percentual_sa", ""),
                 "vl_percentual_sp": r.get("vl_percentual_sp", "")}
                for r in rels
            ],
        })

    @mcp.tool()
    def consultar_hierarquia_sigtap(
        co_grupo: str = "", co_sub_grupo: str = "", competencia: str = ""
    ) -> str:
        """Navega a hierarquia SIGTAP: Grupo > SubGrupo > Forma de Organizacao.

        Sem parametros: lista todos os grupos. Com grupo: lista subgrupos.
        Com subgrupo: lista formas de organizacao.

        Args:
            co_grupo: Codigo do grupo (2 digitos). Ex: '03', '04'.
            co_sub_grupo: Codigo do subgrupo (4 digitos). Ex: '0301'.
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        c = get_client()
        comp = _resolver_comp(c, competencia)

        if not co_grupo:
            grupos = c.sigtap.grupos.list_all(comp)
            return _json({"competencia": comp, "grupos": grupos})

        if not co_sub_grupo:
            subs = c.sigtap.sub_grupo.search("co_grupo", co_grupo, comp, limit=100)
            exact = [s for s in subs if s["co_grupo"] == co_grupo]
            return _json({"competencia": comp, "grupo": co_grupo, "sub_grupos": exact})

        formas = c.sigtap.forma_organizacao.search("co_sub_grupo", co_sub_grupo, comp, limit=100)
        exact = [f for f in formas if f["co_sub_grupo"] == co_sub_grupo]
        return _json({"competencia": comp, "sub_grupo": co_sub_grupo, "formas_organizacao": exact})

    @mcp.tool()
    def consultar_descricao_procedimento(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Retorna a descricao textual completa de um procedimento SIGTAP.

        Inclui indicacoes, contra-indicacoes, orientacoes e detalhes tecnicos.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        descr = c.sigtap.descricao.get_by_id(codigo_procedimento, comp)
        if not descr:
            return _erro(f"Descricao nao encontrada para '{codigo_procedimento}'.")
        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "descricao": descr.get("ds_procedimento", ""),
        })

    @mcp.tool()
    def consultar_regras_condicionadas(
        codigo_procedimento: str, competencia: str = ""
    ) -> str:
        """Lista regras condicionadas vinculadas a um procedimento.

        Retorna regras especiais que condicionam a cobranca do procedimento.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia: Competencia AAAAMM. Default: mais recente.
        """
        codigo_procedimento = _norm_proc(codigo_procedimento)
        c = get_client()
        comp = _resolver_comp(c, competencia)
        rels = c.sigtap.rl_procedimento_regra_cond.list_by_ids([codigo_procedimento], comp)

        regra_codes = [r["co_regra_condicionada"] for r in rels]
        regra_infos = c.sigtap.regra_condicionada.list_by_ids(regra_codes, comp) if regra_codes else []
        regra_map = {rg["co_regra_condicionada"]: rg for rg in regra_infos}

        return _json({
            "procedimento": codigo_procedimento,
            "competencia": comp,
            "regras": [
                {"co_regra": r["co_regra_condicionada"],
                 "no_regra": regra_map.get(r["co_regra_condicionada"], {}).get("no_regra_condicionada", ""),
                 "ds_regra": regra_map.get(r["co_regra_condicionada"], {}).get("ds_regra_condicionada", "")}
                for r in rels
            ],
        })
