"""Tools MCP de inteligencia para analise SIGTAP (busca reversa e historico)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from . import _erro, _json, _resolver_comp

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from ..datasus.client import DatasusClient


def register(mcp: "FastMCP", get_client: Callable[[], "DatasusClient"]) -> None:
    """Registra 2 tools de inteligencia SIGTAP."""

    @mcp.tool()
    def sugerir_procedimentos_por_cid(
        codigo_cid: str, competencia: str = "", limite: int = 30
    ) -> str:
        """Encontra procedimentos que aceitam um determinado CID.

        Dado um diagnostico (CID-10), retorna todos os procedimentos
        que podem ser cobrados com esse CID como diagnostico principal
        ou secundario. Inclui valores para comparacao.

        Util para identificar opcoes de faturamento a partir do diagnostico.

        Args:
            codigo_cid: Codigo CID-10. Ex: 'I10', 'C50.9', 'S72.0'.
            competencia: Competencia AAAAMM. Default: mais recente.
            limite: Maximo de resultados. Default: 30.
        """
        client = get_client()
        comp = _resolver_comp(client, competencia)

        cid_info = client.sigtap.cid.get_by_id(codigo_cid, comp)
        if not cid_info:
            return _erro(f"CID '{codigo_cid}' nao encontrado.")

        rows = client._conn.execute(
            "SELECT DISTINCT co_procedimento, st_principal "
            "FROM rl_procedimento_cid "
            "WHERE co_cid = ? AND dt_competencia = ? "
            f"LIMIT {min(limite, 200)}",
            [codigo_cid, comp],
        )

        if not rows:
            return _json({
                "cid": codigo_cid,
                "no_cid": cid_info.get("no_cid", ""),
                "procedimentos": [],
                "msg": "Nenhum procedimento encontrado para este CID.",
            })

        proc_codes = [r["co_procedimento"] for r in rows]
        procs = client.sigtap.procedimentos.list_by_ids(proc_codes, comp)
        proc_map = {p["co_procedimento"]: p for p in procs}
        principal_map = {r["co_procedimento"]: r["st_principal"] for r in rows}

        procedimentos = []
        for code in proc_codes:
            p = proc_map.get(code, {})
            if not p:
                continue
            vl_total = round(
                float(p.get("vl_sh", 0) or 0)
                + float(p.get("vl_sa", 0) or 0)
                + float(p.get("vl_sp", 0) or 0),
                2,
            )
            procedimentos.append({
                "co_procedimento": code,
                "no_procedimento": p.get("no_procedimento", ""),
                "st_principal": principal_map.get(code, ""),
                "vl_total": vl_total,
                "tp_complexidade": p.get("tp_complexidade", ""),
            })

        procedimentos.sort(key=lambda x: x["vl_total"], reverse=True)

        return _json({
            "cid": codigo_cid,
            "no_cid": cid_info.get("no_cid", ""),
            "competencia": comp,
            "total": len(procedimentos),
            "procedimentos": procedimentos,
        })

    @mcp.tool()
    def comparar_procedimento_competencias(
        codigo_procedimento: str,
        competencia_a: str,
        competencia_b: str,
    ) -> str:
        """Compara um procedimento entre duas competencias SIGTAP.

        Mostra diferencas em valores, CIDs permitidos, habilitacoes
        e servicos exigidos. Util para acompanhar mudancas nas regras
        entre atualizacoes da tabela SIGTAP.

        Args:
            codigo_procedimento: Codigo do procedimento (10 digitos).
            competencia_a: Competencia anterior (AAAAMM). Ex: '202501'.
            competencia_b: Competencia posterior (AAAAMM). Ex: '202602'.
        """
        client = get_client()

        proc_a = client.sigtap.procedimentos.get_by_id(
            codigo_procedimento, competencia_a
        )
        proc_b = client.sigtap.procedimentos.get_by_id(
            codigo_procedimento, competencia_b
        )

        if not proc_a and not proc_b:
            return _erro(
                f"Procedimento '{codigo_procedimento}' nao encontrado "
                f"em nenhuma competencia."
            )

        resultado = {
            "procedimento": codigo_procedimento,
            "competencia_a": competencia_a,
            "competencia_b": competencia_b,
            "existe_a": proc_a is not None,
            "existe_b": proc_b is not None,
            "diferencas": [],
        }

        if not proc_a or not proc_b:
            status = "ADICIONADO" if proc_b else "REMOVIDO"
            proc = proc_b or proc_a
            resultado["diferencas"].append({
                "campo": "status",
                "tipo": status,
                "nome": proc.get("no_procedimento", ""),
            })
            return _json(resultado)

        # Comparar campos
        for campo in [
            "vl_sh", "vl_sa", "vl_sp", "no_procedimento",
            "qt_idade_minima", "qt_idade_maxima",
            "qt_permanencia", "tp_complexidade",
        ]:
            val_a = proc_a.get(campo, "")
            val_b = proc_b.get(campo, "")
            if str(val_a) != str(val_b):
                resultado["diferencas"].append({
                    "campo": campo,
                    "valor_a": val_a,
                    "valor_b": val_b,
                })

        # Comparar CIDs
        cids_a = {
            r["co_cid"]
            for r in client.sigtap.rl_procedimento_cid.list_by_ids(
                [codigo_procedimento], competencia_a
            )
        }
        cids_b = {
            r["co_cid"]
            for r in client.sigtap.rl_procedimento_cid.list_by_ids(
                [codigo_procedimento], competencia_b
            )
        }

        cids_add = cids_b - cids_a
        cids_rem = cids_a - cids_b
        if cids_add:
            resultado["diferencas"].append({
                "campo": "cids_adicionados",
                "quantidade": len(cids_add),
                "codigos": sorted(cids_add)[:20],
            })
        if cids_rem:
            resultado["diferencas"].append({
                "campo": "cids_removidos",
                "quantidade": len(cids_rem),
                "codigos": sorted(cids_rem)[:20],
            })

        # Comparar habilitacoes
        habs_a = {
            r["co_habilitacao"]
            for r in client.sigtap.rl_procedimento_habilitacao.list_by_ids(
                [codigo_procedimento], competencia_a
            )
        }
        habs_b = {
            r["co_habilitacao"]
            for r in client.sigtap.rl_procedimento_habilitacao.list_by_ids(
                [codigo_procedimento], competencia_b
            )
        }
        if habs_a != habs_b:
            resultado["diferencas"].append({
                "campo": "habilitacoes",
                "adicionadas": sorted(habs_b - habs_a),
                "removidas": sorted(habs_a - habs_b),
            })

        # Comparar servicos
        servs_a = {
            (r["co_servico"], r.get("co_classificacao", ""))
            for r in client.sigtap.rl_procedimento_servico.list_by_ids(
                [codigo_procedimento], competencia_a
            )
        }
        servs_b = {
            (r["co_servico"], r.get("co_classificacao", ""))
            for r in client.sigtap.rl_procedimento_servico.list_by_ids(
                [codigo_procedimento], competencia_b
            )
        }
        if servs_a != servs_b:
            resultado["diferencas"].append({
                "campo": "servicos",
                "adicionados": [
                    {"servico": s, "class": cl}
                    for s, cl in sorted(servs_b - servs_a)
                ],
                "removidos": [
                    {"servico": s, "class": cl}
                    for s, cl in sorted(servs_a - servs_b)
                ],
            })

        if not resultado["diferencas"]:
            resultado["resumo"] = "Nenhuma diferenca entre as competencias."
        else:
            resultado["resumo"] = (
                f"{len(resultado['diferencas'])} diferenca(s) encontrada(s)."
            )

        return _json(resultado)
