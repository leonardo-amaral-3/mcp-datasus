"""
Cliente S3/MinIO para acesso aos dados DATASUS (SIGTAP, CNES).

Lê Parquet do bucket-datasus no MinIO local e auto-detecta
a competência mais recente disponível.
"""

import io
import os
from functools import lru_cache

import boto3
import pyarrow.parquet as pq


_BUCKET = os.getenv("DATASUS_BUCKET", "bucket-datasus")
_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID", "minioadmin")
_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "minioadmin")

_client = None


def _get_client():
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
    """Lista competências (AAAAMM) disponíveis para um prefixo (SIGTAP/ ou CNES/)."""
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
    """Retorna a competência mais recente para um prefixo."""
    comps = listar_competencias(prefixo)
    return comps[-1] if comps else None


def ler_parquet(chave: str) -> pq.ParquetFile | None:
    """Baixa um arquivo Parquet do S3 e retorna como pyarrow.Table."""
    s3 = _get_client()
    try:
        resp = s3.get_object(Bucket=_BUCKET, Key=chave)
        dados = resp["Body"].read()
        return pq.read_table(io.BytesIO(dados))
    except s3.exceptions.NoSuchKey:
        return None
    except Exception:
        return None


def listar_arquivos(prefixo: str) -> list[str]:
    """Lista arquivos em um prefixo S3."""
    s3 = _get_client()
    resp = s3.list_objects_v2(Bucket=_BUCKET, Prefix=prefixo)
    return [obj["Key"] for obj in resp.get("Contents", [])]
