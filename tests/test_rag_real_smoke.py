import pytest

from rag.config import rag_settings
from rag.embed import make_embedder
from rag.index import Index, build_index
from rag.ingest import load_documents
from rag.retrieve import make_retriever


@pytest.mark.slow
def test_hybrid_rerank_finds_the_geo_doc_with_real_models(tmp_path):
    s = rag_settings({"rag": {
        "docs_dir": "data/examples/docs",
        "index_dir": str(tmp_path / "index"),
        "embedding": {"model": "BAAI/bge-m3"},
        "generation": {"model": "mlx-community/Qwen2.5-3B-Instruct-4bit"},  # requis par le schéma, jamais chargé
        "retrieval": {"mode": "hybrid", "k": 3, "candidates": 10, "rerank": "BAAI/bge-reranker-v2-m3"},
    }})
    docs = load_documents(s["docs_dir"])
    embedder = make_embedder(s)
    retriever = make_retriever(s, Index(build_index(s, docs, embedder)), embedder)
    assert retriever("Quelle est la capitale de la France ?")[0]["doc_id"] == "geo.md"
