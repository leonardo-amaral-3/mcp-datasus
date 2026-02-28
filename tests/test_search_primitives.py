"""Tests para search_primitives — funções puras de busca RAG.

Camada 1 (ALTO ROI): testa tokenizador, filtros, RRF, decomposição,
parent chunks — tudo sem dependência de ChromaDB ou sentence-transformers.
"""

from __future__ import annotations

from manual_sih_rag.rag.search_primitives import (
    _match_filter,
    decompor_query,
    extrair_filtros_metadata,
    reciprocal_rank_fusion,
    resolver_parent_chunks,
    tokenizar_pt,
)


class TestTokenizarPt:
    def test_lowercase_e_remove_acentos(self):
        tokens = tokenizar_pt("Ação Emergência")
        assert "acao" in tokens
        assert "emergencia" in tokens

    def test_remove_stopwords(self):
        tokens = tokenizar_pt("o procedimento de saúde para o paciente")
        assert "procedimento" in tokens
        assert "saude" in tokens
        assert "paciente" in tokens
        # stopwords removidas
        assert "o" not in tokens
        assert "de" not in tokens
        assert "para" not in tokens

    def test_remove_caracteres_especiais(self):
        tokens = tokenizar_pt("CID-10: I10.0")
        assert "cid" in tokens
        assert "10" in tokens
        assert "i10" in tokens

    def test_ignora_tokens_curtos(self):
        tokens = tokenizar_pt("a é o x y")
        assert len(tokens) == 0

    def test_string_vazia(self):
        assert tokenizar_pt("") == []


class TestExtrairFiltrosMetadata:
    def test_detecta_ano(self):
        filtro = extrair_filtros_metadata("portaria de 2024 sobre OPM")
        assert filtro is not None
        # Deve ter $and com ano e tipo
        if "$and" in filtro:
            chaves = {k for sub in filtro["$and"] for k in sub}
            assert "ano" in chaves
        else:
            assert filtro.get("ano") == "2024" or filtro.get("tipo") is not None

    def test_detecta_portaria(self):
        filtro = extrair_filtros_metadata("portaria sobre internação")
        assert filtro is not None
        if "$and" in filtro:
            tipos = [sub.get("tipo") for sub in filtro["$and"]]
            assert "portaria" in tipos
        else:
            assert filtro.get("tipo") == "portaria"

    def test_detecta_manual(self):
        filtro = extrair_filtros_metadata("manual do SIH sobre AIH")
        assert filtro is not None

    def test_sem_filtro(self):
        assert extrair_filtros_metadata("como funciona o faturamento") is None


class TestMatchFilter:
    def test_match_simples(self):
        assert _match_filter({"tipo": "manual", "ano": "2024"}, {"tipo": "manual"})

    def test_no_match(self):
        assert not _match_filter({"tipo": "portaria"}, {"tipo": "manual"})

    def test_and_filter(self):
        meta = {"tipo": "portaria", "ano": "2024"}
        where = {"$and": [{"tipo": "portaria"}, {"ano": "2024"}]}
        assert _match_filter(meta, where)

    def test_and_filter_parcial(self):
        meta = {"tipo": "portaria", "ano": "2023"}
        where = {"$and": [{"tipo": "portaria"}, {"ano": "2024"}]}
        assert not _match_filter(meta, where)

    def test_campo_ausente(self):
        assert not _match_filter({}, {"tipo": "manual"})


class TestDecomporQuery:
    def test_query_simples(self):
        queries = decompor_query("como preencher AIH", critica_hints={})
        assert "como preencher AIH" in queries
        # Expande sigla AIH
        assert any("autorizacao internacao hospitalar" in q for q in queries)

    def test_query_com_e(self):
        queries = decompor_query(
            "diferença entre SH e SP no procedimento", critica_hints={}
        )
        assert len(queries) >= 2

    def test_query_com_diferenca(self):
        queries = decompor_query(
            "diferença entre cirurgia eletiva e de urgência", critica_hints={}
        )
        assert any("cirurgia eletiva" in q for q in queries)

    def test_deduplica(self):
        queries = decompor_query("teste simples", critica_hints={})
        assert len(queries) == len(set(queries))


class TestReciprocalRankFusion:
    def test_lista_unica(self):
        lista = [("doc1", 0.9), ("doc2", 0.8), ("doc3", 0.7)]
        result = reciprocal_rank_fusion(lista, k=60)
        ids = [r[0] for r in result]
        assert ids == ["doc1", "doc2", "doc3"]

    def test_fusao_duas_listas(self):
        lista1 = [("doc1", 0.9), ("doc2", 0.8)]
        lista2 = [("doc2", 0.95), ("doc3", 0.7)]
        result = reciprocal_rank_fusion(lista1, lista2, k=60)
        ids = [r[0] for r in result]
        # doc2 aparece nas duas listas, deve ter score maior
        assert ids[0] == "doc2"

    def test_lista_vazia(self):
        assert reciprocal_rank_fusion([], k=60) == []

    def test_k_parameter(self):
        lista = [("doc1", 0.9)]
        result_60 = reciprocal_rank_fusion(lista, k=60)
        result_1 = reciprocal_rank_fusion(lista, k=1)
        # score = 1/(k+1), entao k menor = score maior
        assert result_1[0][1] > result_60[0][1]


class TestResolverParentChunks:
    def test_sem_parent_map(self):
        resultados = [("c1", 0.9), ("c2", 0.8)]
        result = resolver_parent_chunks(resultados, {})
        assert [r[0] for r in result] == ["c1", "c2"]

    def test_com_parent_map(self):
        resultados = [("c1", 0.9), ("c2", 0.8), ("c3", 0.7)]
        parent_map = {"c1": "p1", "c2": "p1", "c3": "p2"}
        result = resolver_parent_chunks(resultados, parent_map)
        ids = [r[0] for r in result]
        # c1 e c2 mapeiam para p1, pega o maior score (0.9)
        assert "p1" in ids
        assert "p2" in ids
        assert len(ids) == 2
        # p1 deve vir primeiro (score 0.9 > 0.7)
        assert ids[0] == "p1"

    def test_parent_score_maximo(self):
        resultados = [("c1", 0.5), ("c2", 0.9)]
        parent_map = {"c1": "p1", "c2": "p1"}
        result = resolver_parent_chunks(resultados, parent_map)
        assert result[0][1] == 0.9  # maior score entre filhos
