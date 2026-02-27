"""DuckDB connection manager with S3/MinIO integration via httpfs."""

from __future__ import annotations

from typing import Any

import duckdb

from ..config import S3Config
from ..shared.log import get_logger
from .schemas import CNES_TABLES, SIGTAP_TABLES

log = get_logger("datasus.connection")


class DuckDBConnection:
    """DuckDB in-memory com httpfs para acesso a Parquet no MinIO.

    Registra views para todas as tabelas SIGTAP e CNES,
    permitindo queries SQL diretamente sobre os dados remotos.
    """

    def __init__(self, s3_config: S3Config) -> None:
        self._s3 = s3_config
        self._conn = duckdb.connect()
        self._views_registered = False
        self._setup_httpfs()

    def _setup_httpfs(self) -> None:
        self._conn.install_extension("httpfs")
        self._conn.load_extension("httpfs")
        endpoint = self._s3.endpoint.replace("http://", "").replace("https://", "")
        self._conn.execute(f"SET s3_endpoint='{endpoint}'")
        self._conn.execute(f"SET s3_access_key_id='{self._s3.access_key}'")
        self._conn.execute(f"SET s3_secret_access_key='{self._s3.secret_key}'")
        ssl = "true" if self._s3.use_ssl else "false"
        self._conn.execute(f"SET s3_use_ssl={ssl}")
        self._conn.execute("SET s3_url_style='path'")
        log.info("httpfs configurado para %s", self._s3.endpoint)

    def register_views(self) -> None:
        """Registra views DuckDB para todos os Parquet no S3."""
        if self._views_registered:
            return
        bucket = self._s3.bucket

        for table_name in SIGTAP_TABLES:
            path = f"s3://{bucket}/SIGTAP/*/{table_name}.parquet"
            self._conn.execute(
                f"CREATE OR REPLACE VIEW {table_name} AS "
                f"SELECT * FROM read_parquet('{path}')"
            )
        log.info("Registradas %d views SIGTAP", len(SIGTAP_TABLES))

        for view_name, file_name in CNES_TABLES.items():
            path = f"s3://{bucket}/CNES/*/{file_name}"
            self._conn.execute(
                f"CREATE OR REPLACE VIEW {view_name} AS "
                f"SELECT * FROM read_parquet('{path}')"
            )
        log.info("Registradas %d views CNES", len(CNES_TABLES))

        self._views_registered = True

    def execute(
        self, sql: str, params: list[Any] | None = None
    ) -> list[dict[str, Any]]:
        """Executa SQL e retorna lista de dicts.

        Usa conn.execute() diretamente (nao cursor()) porque
        DuckDB 1.4+ nao propaga configs httpfs para cursores filhos.
        """
        if params:
            result = self._conn.execute(sql, params)
        else:
            result = self._conn.execute(sql)
        if result.description is None:
            return []
        columns = [desc[0] for desc in result.description]
        return [dict(zip(columns, row)) for row in result.fetchall()]

    def execute_one(
        self, sql: str, params: list[Any] | None = None
    ) -> dict[str, Any] | None:
        """Executa SQL e retorna primeiro resultado ou None."""
        rows = self.execute(sql, params)
        return rows[0] if rows else None

    def health_check(self) -> bool:
        """Testa conexao com DuckDB e acesso ao S3/MinIO."""
        try:
            result = self.execute("SELECT 1 AS ok")
            return bool(result and result[0].get("ok") == 1)
        except Exception:
            return False

    def close(self) -> None:
        self._conn.close()
