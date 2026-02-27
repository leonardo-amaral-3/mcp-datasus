"""Tools MCP legadas — SIGTAP/CNES via boto3 (compatibilidade retroativa)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import _erro, _json

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
        from manual_sih_rag.legacy.sigtap_client import consultar_procedimento as _consultar

        try:
            resultado = _consultar(codigo)
        except RuntimeError as e:
            return _erro(str(e))

        if not resultado:
            return _erro(f"Procedimento '{codigo}' nao encontrado no SIGTAP.")
        return _json(resultado)

    @mcp.tool()
    def buscar_procedimento(nome: str, grupo: str = "") -> str:
        """Busca procedimentos SIGTAP por nome.

        Retorna lista de procedimentos cujo nome contem o termo buscado.
        Filtro opcional por codigo de grupo (2 primeiros digitos do codigo).

        Args:
            nome: Termo de busca no nome do procedimento. Ex: 'colecistectomia', 'parto'.
            grupo: Filtro opcional por prefixo de grupo. Ex: '03' para clinicos, '04' para cirurgicos.
        """
        from manual_sih_rag.legacy.sigtap_client import buscar_procedimentos

        try:
            resultados = buscar_procedimentos(nome, grupo=grupo)
        except RuntimeError as e:
            return _erro(str(e))

        if not resultados:
            return _json({"mensagem": f"Nenhum procedimento encontrado para '{nome}'."})
        return _json(resultados)

    @mcp.tool()
    def info_sigtap() -> str:
        """Retorna informacoes sobre os dados SIGTAP carregados.

        Mostra competencia, total de procedimentos e lista de grupos.
        Util para verificar se os dados estao disponiveis e qual competencia esta carregada.
        """
        from manual_sih_rag.legacy.sigtap_client import info

        try:
            return _json(info())
        except RuntimeError as e:
            return _erro(str(e))

    @mcp.tool()
    def consultar_cnes(codigo_cnes: str) -> str:
        """Consulta dados operacionais de um estabelecimento CNES.

        Retorna leitos (tipos e quantidades SUS), servicos oferecidos,
        habilitacoes e resumo de profissionais por ocupacao.
        Dados lidos do MinIO (Parquet).

        Args:
            codigo_cnes: Codigo CNES do estabelecimento (7 digitos). Ex: '2077485'.
        """
        from manual_sih_rag.legacy.cnes_client import consultar_cnes as _consultar

        try:
            resultado = _consultar(codigo_cnes)
        except RuntimeError as e:
            return _erro(str(e))

        if not resultado:
            return _erro(f"CNES '{codigo_cnes}' nao encontrado nos dados operacionais.")
        return _json(resultado)

    @mcp.tool()
    def buscar_profissionais_cnes(codigo_cnes: str, ocupacao: str = "") -> str:
        """Lista profissionais vinculados a um estabelecimento CNES.

        Retorna codigo de ocupacao, identificador SUS e carga horaria.
        Filtro opcional por codigo de ocupacao (CBO).

        Args:
            codigo_cnes: Codigo CNES do estabelecimento (7 digitos). Ex: '2077485'.
            ocupacao: Codigo CBO opcional para filtrar. Ex: '225142' (medico cirurgiao).
        """
        from manual_sih_rag.legacy.cnes_client import buscar_profissionais

        try:
            profs = buscar_profissionais(codigo_cnes, co_ocupacao=ocupacao)
        except RuntimeError as e:
            return _erro(str(e))

        if not profs:
            msg = f"Nenhum profissional encontrado para CNES '{codigo_cnes}'"
            if ocupacao:
                msg += f" com ocupacao '{ocupacao}'"
            return _json({"mensagem": msg + "."})
        return _json(profs)

    @mcp.tool()
    def info_cnes() -> str:
        """Retorna informacoes sobre os dados CNES carregados.

        Mostra competencia e totais de estabelecimentos com leitos, servicos,
        habilitacoes e profissionais.
        """
        from manual_sih_rag.legacy.cnes_client import info

        try:
            return _json(info())
        except RuntimeError as e:
            return _erro(str(e))
