"""Configuracao centralizada via variaveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VERSION = "2.1.0"
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")


@dataclass(frozen=True)
class S3Config:
    endpoint: str = field(
        default_factory=lambda: os.getenv("S3_ENDPOINT", "http://localhost:9000")
    )
    access_key: str = field(
        default_factory=lambda: os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
    )
    secret_key: str = field(
        default_factory=lambda: os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")
    )
    bucket: str = field(
        default_factory=lambda: os.getenv("DATASUS_BUCKET", "bucket-datasus")
    )
    use_ssl: bool = False


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
