"""DATASUS data access layer — SIGTAP + CNES via DuckDB over Parquet/S3."""

__all__ = ["DatasusClient"]


def __getattr__(name: str):
    if name == "DatasusClient":
        from .client import DatasusClient
        return DatasusClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
