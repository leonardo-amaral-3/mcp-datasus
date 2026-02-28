"""Characterization tests para _formatar / _json / _erro.

Documenta o formato de saida usado por todas as tools MCP.
"""

from manual_sih_rag.tools import _erro, _json


class TestJson:
    """Characterization: _json() formata dicts como texto legivel."""

    def test_dict_simples(self):
        result = _json({"conforme": True, "nome": "teste"})
        assert "Conforme: Sim" in result
        assert "Nome: teste" in result

    def test_dict_com_valor_none(self):
        """Characterization: chaves sem rotulo sao capitalizadas."""
        result = _json({"campo": None})
        assert "Campo: -" in result

    def test_dict_com_bool_false(self):
        result = _json({"valido": False})
        assert "Válido: Não" in result

    def test_lista_de_dicts(self):
        result = _json([{"a": 1}, {"a": 2}])
        assert "resultados" in result.lower() or "[1]" in result

    def test_lista_de_strings(self):
        result = _json({"items": ["x", "y"]})
        assert "- x" in result
        assert "- y" in result

    def test_dict_aninhado(self):
        result = _json({"procedimento": {"codigo": "123", "nome": "abc"}})
        assert "Procedimento:" in result
        assert "Código: 123" in result

    def test_lista_vazia(self):
        result = _json({"alertas": []})
        assert "(nenhum)" in result

    def test_rotulos_conhecidos(self):
        result = _json({"vl_sh": 100, "vl_sa": 50})
        assert "Valor SH: 100" in result
        assert "Valor SA: 50" in result


class TestErro:
    def test_formato(self):
        assert _erro("falha") == "Erro: falha"
