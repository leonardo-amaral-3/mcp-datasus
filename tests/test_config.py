"""Tests para config.py — validacao de credenciais e guardrails."""

from __future__ import annotations

import os
from unittest.mock import patch

from manual_sih_rag.config import S3Config, load_settings


class TestS3Config:
    """Verifica comportamento de S3Config com env vars."""

    def test_le_de_env_vars(self):
        env = {
            "AWS_ACCESS_KEY_ID": "real-key",
            "AWS_SECRET_ACCESS_KEY": "real-secret",
            "S3_ENDPOINT": "http://prod:9000",
            "DATASUS_BUCKET": "prod-bucket",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = S3Config()
            assert cfg.access_key == "real-key"
            assert cfg.secret_key == "real-secret"
            assert cfg.endpoint == "http://prod:9000"
            assert cfg.bucket == "prod-bucket"

    def test_defaults_quando_env_ausente(self):
        env_keys = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                     "S3_ENDPOINT", "DATASUS_BUCKET"]
        cleaned = {k: v for k, v in os.environ.items() if k not in env_keys}
        with patch.dict(os.environ, cleaned, clear=True):
            cfg = S3Config()
            assert cfg.access_key == "minioadmin"
            assert cfg.secret_key == "minioadmin"

    def test_frozen(self):
        cfg = S3Config()
        try:
            cfg.access_key = "hack"  # type: ignore[misc]
            assert False, "Deveria ser frozen"
        except AttributeError:
            pass

    def test_warning_quando_credenciais_default(self, caplog):
        """Guardrail: log warning quando usando minioadmin."""
        env_keys = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
        cleaned = {k: v for k, v in os.environ.items() if k not in env_keys}
        with patch.dict(os.environ, cleaned, clear=True):
            import logging
            with caplog.at_level(logging.WARNING, logger="manual_sih_rag.config"):
                S3Config()
            assert "credenciais default" in caplog.text.lower()

    def test_sem_warning_com_credenciais_reais(self, caplog):
        env = {
            "AWS_ACCESS_KEY_ID": "real-key",
            "AWS_SECRET_ACCESS_KEY": "real-secret",
        }
        with patch.dict(os.environ, env, clear=False):
            import logging
            with caplog.at_level(logging.WARNING, logger="manual_sih_rag.config"):
                S3Config()
            assert "credenciais default" not in caplog.text.lower()
