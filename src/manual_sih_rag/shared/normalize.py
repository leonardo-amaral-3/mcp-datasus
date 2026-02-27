"""Utilitarios de normalizacao de texto."""

import re
import unicodedata


def normalizar(texto: str) -> str:
    """Remove acentos, lowercase, colapsa espacos."""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().strip()
    texto = re.sub(r"\s+", " ", texto)
    return texto
