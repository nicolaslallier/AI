import pytest

from fakes import HashEmbedder, OverlapReranker, make_cfg
from rag.config import rag_settings
from rag.index import build_index, open_index
from rag.ingest import load_documents
from rag.retrieve import Retriever, rrf


def test_rrf_orders_by_fused_rank_and_dedups():
    out = rrf([["a", "b", "c"], ["b", "d"]])
    assert [i for i, _ in out] == ["b", "a", "d", "c"]
    assert len({i for i, _ in out}) == 4
    assert out[0][1] > out[1][1]


def test_rrf_empty_ranking_is_identity():
    assert [i for i, _ in rrf([["a", "b"], []])] == ["a", "b"]
    assert rrf([[], []]) == []


@pytest.fixture
def idx(tmp_path):
    s = rag_settings(make_cfg(tmp_path))
    docs = load_documents(s["docs_dir"])
    build_index(s, docs, HashEmbedder())
    return open_index(s, docs), HashEmbedder()


def test_dense_mode_matches_index_search(idx):
    index, emb = idx
    got = Retriever(index, emb, "dense", 2, 2)("capitale de la France")
    assert [p["id"] for p in got] == [p["id"] for p in index.search(emb.embed_query("capitale de la France"), 2)]


def test_hybrid_has_unique_ids_and_at_most_k(idx):
    index, emb = idx
    got = Retriever(index, emb, "hybrid", 3, 10)("capitale de la France")
    ids = [p["id"] for p in got]
    assert len(ids) == len(set(ids)) and len(ids) <= 3
    assert [p["score"] for p in got] == sorted((p["score"] for p in got), reverse=True)


@pytest.mark.parametrize("q", ["la de", "la de ?"])
def test_hybrid_falls_back_to_dense_when_fts_is_empty(idx, q):
    index, emb = idx
    got = Retriever(index, emb, "hybrid", 2, 10)(q)
    assert [p["id"] for p in got] == [p["id"] for p in Retriever(index, emb, "dense", 2, 10)(q)]


def test_hybrid_survives_fts_syntax_chars(idx):
    index, emb = idx
    ids = [p["id"] for p in Retriever(index, emb, "hybrid", 3, 10)('"(:* France')]
    assert len(ids) == 3 and len(set(ids)) == 3


def test_hybrid_rerank_pool_capped_at_candidates():
    def ps(*ids):
        return [{"id": i, "text": i, "score": 0.0} for i in ids]

    class DisjointIndex:  # dense et lexical disjoints : l'union fait 2 * candidates
        def search(self, vec, n):
            return ps("a", "b", "c")[:n]

        def search_text(self, query, n):
            return ps("x", "y", "z")[:n]

    seen = []

    class Spy(OverlapReranker):
        def score(self, query, texts):
            seen.append(len(texts))
            return super().score(query, texts)

    Retriever(DisjointIndex(), HashEmbedder(), "hybrid", 1, 2, reranker=Spy())("q")
    assert seen == [2]


def test_k_larger_than_corpus_does_not_crash(idx):
    index, emb = idx
    assert Retriever(index, emb, "hybrid", 500, 500)("France")


def test_rerank_reorders_and_replaces_score(idx):
    index, emb = idx
    q = "capitale de la France"
    got = Retriever(index, emb, "dense", 2, 10, reranker=OverlapReranker())(q)
    assert len(got) == 2
    assert got[0]["score"] >= got[1]["score"]
    texts = [p["text"] for p in got]
    assert OverlapReranker().score(q, texts) == [p["score"] for p in got]
