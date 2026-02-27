"""Tools MCP legadas — SIGTAP/CNES via boto3 (compatibilidade retroativa)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: "FastMCP") -> None:
    """Registra 6 tools legadas SIGTAP/CNES no servidor MCP."""

    @mcp.tool()
    def consultar_procedimento(codigo: str) -> str:
        """Consulta um procedimento SIGTAP pelo codigo (10 digitos).

        Retorna nome, valores (SH, SA, SP, total hospitalar), idades, permanencia e competencia.
        Dados lidos do MinIO (Parquet).

        Args:
            codigo: Codigo do procedimento (10 digitos). Ex: '0301010072'.
        """
        from sigtap_client import consultar_procedimento as _consultar

        try:
            resultado = _consultar(codigo)
        except RuntimeError as e:
            return json.dumps({"erro": str(e)}, ensure_ascii=False)

        if not resultado:
            return json.dumps(
                {"erro": f"Procedimento '{codigo}' nao encontrado no SIGTAP."},
                ensure_ascii=False,
            )
        return json.dumps(resultado, ensure_ascii=False, indent=2)

    @mcp.tool()
    def buscar_procedimento(nome: str, grupo: str = "") -> str:
        """Busca procedimentos SIGTAP por nome.

        Retorna lista de procedimentos cujo nome contem o termo buscado.
        Filtro opcional por codigo de grupo (2 primeiros digitos do codigo).

        Args:
            nome: Termo de busca no nome do procedimento. Ex: 'colecistectomia', 'parto'.
            grupo: Filtro opcional por prefixo de grupo. Ex: '03' para clinicos, '04' para cirurgicos.
        """
        from sigtap_client import buscar_procedimentos

        try:
            resultados = buscar_procedimentos(nome, grupo=grupo)
        except RuntimeError as e:
            return json.dumps({"erro": str(e)}, ensure_ascii=False)

        if not resultados:
            return json.dumps(
                {"mensagem": f"Nenhum procedimento encontrado para '{nome}'."},
                ensure_ascii=False,
            )
        return json.dumps(resultados, ensure_ascii=False, indent=2)

    @mcp.tool()
    def info_sigtap() -> str:
        """Retorna informacoes sobre os dados SIGTAP carregados.

        Mostra competencia, total de procedimentos e lista de grupos.
        Util para verificar se os dados estao disponiveis e qual competencia esta carregada.
        """
        from sigtap_client import info

        try:
            return json.dumps(info(), ensure_ascii=False, indent=2)
        except RuntimeError as e:
            return json.dumps({"erro": str(e)}, ensure_ascii=False)

    @mcp.tool()
    def consultar_cnes(codigo_cnes: str) -> str:
        """Consulta dados operacionais de um estabelecimento CNES.

        Retorna leitos (tipos e quantidades SUS), servicos oferecidos,
        habilitacoes e resumo de profissionais por ocupacao.
        Dados lidos do MinIO (Parquet).

        Args:
            codigo_cnes: Codigo CNES do estabelecimento (7 digitos). Ex: '2077485'.
        """
        from cnes_client import consultar_cnes as _consultar

        try:
            resultado = _consultar(codigo_cnes)
        except RuntimeError as e:
            return json.dumps({"erro": str(e)}, ensure_ascii=False)

        if not resultado:
            return json.dumps(
                {"erro": f"CNES '{codigo_cnes}' nao encontrado nos dados operacionais."},
                ensure_ascii=False,
            )
        return json.dumps(resultado, ensure_ascii=False, indent=2)

    @mcp.tool()
    def buscar_profissionais_cnes(codigo_cnes: str, ocupacao: str = "") -> str:
        """Lista profissionais vinculados a um estabelecimento CNES.

        Retorna codigo de ocupacao, identificador SUS e carga horaria.
        Filtro opcional por codigo de ocupacao (CBO).

        Args:
            codigo_cnes: Codigo CNES do estabelecimento (7 digitos). Ex: '2077485'.
            ocupacao: Codigo CBO opcional para filtrar. Ex: '225142' (medico cirurgiao).
        """
        from cnes_client import buscar_profissionais

        try:
            profs = buscar_profissionais(codigo_cnes, co_ocupacao=ocupacao)
        except RuntimeError as e:
            return json.dumps({"erro": str(e)}, ensure_ascii=False)

        if not profs:
            msg = f"Nenhum profissional encontrado para CNES '{codigo_cnes}'"
            if ocupacao:
                msg += f" com ocupacao '{ocupacao}'"
            return json.dumps({"mensagem": msg + "."}, ensure_ascii=False)
        return json.dumps(profs, ensure_ascii=False, indent=2)

    @mcp.tool()
    def info_cnes() -> str:
        """Retorna informacoes sobre os dados CNES carregados.

        Mostra competencia e totais de estabelecimentos com leitos, servicos,
        habilitacoes e profissionais.
        """
        from cnes_client import info

        try:
            return json.dumps(info(), ensure_ascii=False, indent=2)
        except RuntimeError as e:
            return json.dumps({"erro": str(e)}, ensure_ascii=False)
