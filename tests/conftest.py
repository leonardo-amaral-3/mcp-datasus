"""Shared fixtures for manual-sih-rag tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from manual_sih_rag.config import S3Config


@pytest.fixture()
def s3_config() -> S3Config:
    """S3Config com valores de teste (nunca minioadmin)."""
    return S3Config(
        endpoint="http://test-minio:9000",
        access_key="TEST_ACCESS_KEY",
        secret_key="TEST_SECRET_KEY",
        bucket="test-bucket",
        use_ssl=False,
    )


@pytest.fixture()
def mock_duckdb_conn():
    """Mock de duckdb.connect() para testes sem I/O."""
    conn = MagicMock()
    conn.execute.return_value = conn
    conn.description = None
    conn.fetchall.return_value = []
    return conn
