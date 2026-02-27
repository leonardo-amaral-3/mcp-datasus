"""DatasusClient — ponto de entrada para acesso a dados DATASUS.

Segue o padrao do processos-core DatasusClient:
- DI via construtor (connection, cache, metrics)
- Namespaces: sigtap, cnes
- Metricas centralizadas
"""

from __future__ import annotations

from ..config import S3Config, Settings
from ..shared.log import get_logger
from .cache import QueryCache
from .cnes.namespace import CnesNamespace
from .connection import DuckDBConnection
from .metrics import DatasusMetrics, MetricsCollector
from .sigtap.namespace import SigtapNamespace

log = get_logger("datasus.client")


class DatasusClient:
    """Cliente unificado para consulta a dados DATASUS (SIGTAP + CNES).

    Uso:
        from manual_sih_rag.config import load_settings
        from manual_sih_rag.datasus import DatasusClient

        settings = load_settings()
        client = DatasusClient.from_settings(settings)

        proc = client.sigtap.procedimentos.get_by_id("0301010072", "202602")
        leitos = client.cnes.leitos.list_by_cnes("2077485", "202602")
    """

    def __init__(
        self,
        conn: DuckDBConnection,
        cache: QueryCache | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._conn = conn
        self._metrics = metrics or MetricsCollector()
        self._cache = cache or QueryCache()

        self.sigtap = SigtapNamespace(conn, self._cache, self._metrics)
        self.cnes = CnesNamespace(conn, self._cache, self._metrics)

        conn.register_views()
        log.info("DatasusClient inicializado")

    @classmethod
    def from_settings(cls, settings: Settings) -> DatasusClient:
        """Cria DatasusClient a partir de Settings."""
        conn = DuckDBConnection(settings.s3)
        cache = QueryCache(ttl_seconds=settings.cache_ttl_seconds)
        metrics = MetricsCollector()
        return cls(conn, cache, metrics)

    @classmethod
    def from_s3_config(cls, s3_config: S3Config) -> DatasusClient:
        """Cria DatasusClient a partir de S3Config."""
        conn = DuckDBConnection(s3_config)
        return cls(conn)

    @property
    def metrics(self) -> DatasusMetrics:
        return self._metrics.snapshot

    def test_connection(self) -> bool:
        """Testa conexao com DuckDB e S3."""
        try:
            self._conn.execute("SELECT 1")
            log.info("Conexao DuckDB OK")
            return True
        except Exception as e:
            log.error("Falha na conexao: %s", e)
            return False

    def ultima_competencia(self, fonte: str = "SIGTAP") -> str:
        """Retorna a competencia mais recente disponivel."""
        cache_key = f"_ultima_comp_{fonte}"
        if self._cache and self._cache.has(cache_key):
            return self._cache.get(cache_key)
        table = "tb_procedimento" if fonte == "SIGTAP" else "tb_profissional_cnes"
        rows = self._conn.execute(
            f"SELECT MAX(dt_competencia) as comp FROM {table}"
        )
        comp = rows[0]["comp"] if rows else ""
        if self._cache:
            self._cache.set(cache_key, comp)
        return comp

    def close(self) -> None:
        self._conn.close()
