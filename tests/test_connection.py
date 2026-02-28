"""Characterization tests para DuckDBConnection._setup_httpfs.

Captura o comportamento atual antes de sanitizar credenciais.
London School: mock de duckdb.connect(), sem I/O real.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from manual_sih_rag.config import S3Config
from manual_sih_rag.datasus.connection import DuckDBConnection


class TestSetupHttpfs:
    """Characterization: quais comandos _setup_httpfs emite."""

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_uses_create_secret(self, mock_connect, s3_config):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        DuckDBConnection(s3_config)

        mock_conn.install_extension.assert_called_once_with("httpfs")
        mock_conn.load_extension.assert_called_once_with("httpfs")

        calls = [c for c in mock_conn.execute.call_args_list]
        sql_strs = [c.args[0] for c in calls]

        secret_calls = [s for s in sql_strs if "CREATE SECRET" in s]
        assert len(secret_calls) == 1, "Deve usar CREATE SECRET (nao SET)"
        secret_sql = secret_calls[0]
        assert "TYPE S3" in secret_sql
        assert "KEY_ID" in secret_sql
        assert "SECRET" in secret_sql
        assert "ENDPOINT" in secret_sql
        assert "URL_STYLE" in secret_sql

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_strips_http_prefix_from_endpoint(self, mock_connect, s3_config):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        DuckDBConnection(s3_config)

        calls = mock_conn.execute.call_args_list
        secret_sql = [c.args[0] for c in calls if "CREATE SECRET" in c.args[0]][0]
        assert "http://" not in secret_sql, "Endpoint deve ter prefixo removido"
        assert "test-minio:9000" in secret_sql

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_ssl_false_when_config_false(self, mock_connect, s3_config):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        DuckDBConnection(s3_config)

        calls = mock_conn.execute.call_args_list
        secret_sql = [c.args[0] for c in calls if "CREATE SECRET" in c.args[0]][0]
        assert "USE_SSL false" in secret_sql

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_credentials_in_create_secret(self, mock_connect, s3_config):
        """Credenciais sao passadas via CREATE SECRET."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        DuckDBConnection(s3_config)

        secret_sql = [
            c.args[0] for c in mock_conn.execute.call_args_list
            if "CREATE SECRET" in c.args[0]
        ][0]
        assert "TEST_ACCESS_KEY" in secret_sql
        assert "TEST_SECRET_KEY" in secret_sql


class TestExecute:
    """Characterization: DuckDBConnection.execute()."""

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_returns_list_of_dicts(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        db = DuckDBConnection(S3Config(
            endpoint="http://x:9000",
            access_key="k",
            secret_key="s",
        ))

        mock_result = MagicMock()
        mock_result.description = [("col_a",), ("col_b",)]
        mock_result.fetchall.return_value = [(1, "x"), (2, "y")]
        mock_conn.execute.return_value = mock_result

        rows = db.execute("SELECT 1")
        assert rows == [{"col_a": 1, "col_b": "x"}, {"col_a": 2, "col_b": "y"}]

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_returns_empty_list_when_no_description(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        db = DuckDBConnection(S3Config(
            endpoint="http://x:9000",
            access_key="k",
            secret_key="s",
        ))

        mock_result = MagicMock()
        mock_result.description = None
        mock_conn.execute.return_value = mock_result

        assert db.execute("CREATE TABLE x") == []

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_passes_params_to_duckdb(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        db = DuckDBConnection(S3Config(
            endpoint="http://x:9000",
            access_key="k",
            secret_key="s",
        ))

        mock_result = MagicMock()
        mock_result.description = [("ok",)]
        mock_result.fetchall.return_value = [(1,)]
        mock_conn.execute.return_value = mock_result

        db.execute("SELECT ? AS ok", [42])
        mock_conn.execute.assert_called_with("SELECT ? AS ok", [42])


class TestHealthCheck:
    """Characterization: health_check()."""

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_returns_true_on_success(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        db = DuckDBConnection(S3Config(
            endpoint="http://x:9000", access_key="k", secret_key="s",
        ))

        mock_result = MagicMock()
        mock_result.description = [("ok",)]
        mock_result.fetchall.return_value = [(1,)]
        mock_conn.execute.return_value = mock_result

        assert db.health_check() is True

    @patch("manual_sih_rag.datasus.connection.duckdb.connect")
    def test_returns_false_on_exception(self, mock_connect):
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        db = DuckDBConnection(S3Config(
            endpoint="http://x:9000", access_key="k", secret_key="s",
        ))

        mock_conn.execute.side_effect = Exception("boom")
        assert db.health_check() is False
