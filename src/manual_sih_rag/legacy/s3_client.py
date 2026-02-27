"""S3/MinIO client for DATASUS data access (SIGTAP, CNES).

Reads Parquet from bucket-datasus in local MinIO and auto-detects
the most recent available competencia.
"""

from __future__ import annotations

import io
import os
from typing import Any

import boto3
import pyarrow.parquet as pq

_BUCKET = os.getenv("DATASUS_BUCKET", "bucket-datasus")
_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")

_client: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=_ENDPOINT,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
        )
    return _client


def listar_competencias(prefixo: str) -> list[str]:
    """List competencias (YYYYMM) available for a prefix (SIGTAP/ or CNES/)."""
    s3 = _get_client()
    prefixo = prefixo.rstrip("/") + "/"
    resp = s3.list_objects_v2(Bucket=_BUCKET, Prefix=prefixo, Delimiter="/")
    comps = []
    for cp in resp.get("CommonPrefixes", []):
        parte = cp["Prefix"].rstrip("/").split("/")[-1]
        if parte.isdigit() and len(parte) == 6:
            comps.append(parte)
    return sorted(comps)


def ultima_competencia(prefixo: str) -> str | None:
    """Return the most recent competencia for a prefix."""
    comps = listar_competencias(prefixo)
    return comps[-1] if comps else None


def ler_parquet(chave: str) -> Any:
    """Download a Parquet file from S3 and return as pyarrow.Table."""
    s3 = _get_client()
    try:
        resp = s3.get_object(Bucket=_BUCKET, Key=chave)
        dados = resp["Body"].read()
        return pq.read_table(io.BytesIO(dados))
    except Exception:
        return None


def listar_arquivos(prefixo: str) -> list[str]:
    """List files under an S3 prefix."""
    s3 = _get_client()
    resp = s3.list_objects_v2(Bucket=_BUCKET, Prefix=prefixo)
    return [obj["Key"] for obj in resp.get("Contents", [])]
