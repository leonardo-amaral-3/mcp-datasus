"""Characterization tests para _norm_proc.

Documenta o comportamento atual da normalizacao de codigos
de procedimento SIGTAP (10 digitos SIH → 9 digitos Parquet).
"""

from manual_sih_rag.tools import _norm_proc


class TestNormProc:
    """Characterization: _norm_proc() remove zero leading de 10 digitos."""

    def test_10_digitos_com_zero_leading(self):
        assert _norm_proc("0304010390") == "304010390"

    def test_9_digitos_sem_mudanca(self):
        assert _norm_proc("304010390") == "304010390"

    def test_10_digitos_sem_zero_leading_nao_altera(self):
        assert _norm_proc("1234567890") == "1234567890"

    def test_strip_espacos(self):
        assert _norm_proc("  0304010390  ") == "304010390"

    def test_string_vazia(self):
        assert _norm_proc("") == ""

    def test_codigo_curto(self):
        assert _norm_proc("12345") == "12345"

    def test_com_ponto_e_hifen(self):
        """Nota: _norm_proc NAO processa pontos/hifens. So strip+leading zero."""
        assert _norm_proc("03.04.01.039-0") == "03.04.01.039-0"
