"""Configuracao centralizada via variaveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VERSION = "2.1.0"
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")


_DEV_CRED = "minioadmin"


@dataclass(frozen=True)
class S3Config:
    endpoint: str = field(
        default_factory=lambda: os.getenv("S3_ENDPOINT", "http://localhost:9000")
    )
    access_key: str = field(
        default_factory=lambda: os.getenv("AWS_ACCESS_KEY_ID", _DEV_CRED)
    )
    secret_key: str = field(
        default_factory=lambda: os.getenv("AWS_SECRET_ACCESS_KEY", _DEV_CRED)
    )
    bucket: str = field(
        default_factory=lambda: os.getenv("DATASUS_BUCKET", "bucket-datasus")
    )
    use_ssl: bool = False

    def __post_init__(self) -> None:
        import logging

        if self.access_key == _DEV_CRED or self.secret_key == _DEV_CRED:
            logging.getLogger("manual_sih_rag.config").warning(
                "S3Config usando credenciais default de desenvolvimento. "
                "Defina AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY para producao."
            )


@dataclass(frozen=True)
class ChromaConfig:
    host: str = field(
        default_factory=lambda: os.getenv("CHROMA_HOST", "localhost")
    )
    port: int = field(
        default_factory=lambda: int(os.getenv("CHROMA_PORT", "8000"))
    )


@dataclass(frozen=True)
class Settings:
    s3: S3Config = field(default_factory=S3Config)
    chroma: ChromaConfig = field(default_factory=ChromaConfig)
    max_connections: int = 4
    cache_ttl_seconds: int = 3600


def load_settings() -> Settings:
    """Carrega settings a partir de variaveis de ambiente."""
    return Settings()
