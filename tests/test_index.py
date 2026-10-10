import pytest

from fakes import HashEmbedder, make_cfg
from rag.config import rag_settings
from rag.index import build_index, index_key, open_index
from rag.ingest import load_documents


@pytest.fixture
def setup(tmp_path):
    s = rag_settings(make_cfg(tmp_path))
    return s, load_documents(s["docs_dir"])


def test_search_returns_best_chunk_first(setup):
    s, docs = setup
    emb = HashEmbedder()
    build_index(s, docs, emb)
    hits = open_index(s, docs).search(emb.embed_query("capitale de la France"), 2)
    assert len(hits) == 2
    assert hits[0]["doc_id"] == "geo.md" and hits[0]["id"] == "geo.md#0"
    assert hits[0]["score"] >= hits[1]["score"]
    assert {"text", "start", "end"} <= set(hits[0])


def test_open_without_index_names_the_command(setup):
    s, docs = setup
    with pytest.raises(ValueError, match="rag.index"):
        open_index(s, docs)


def test_modified_document_invalidates_index(setup):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    changed = [dict(docs[0], text=docs[0]["text"] + " modifié")] + docs[1:]
    assert index_key(s, changed) != index_key(s, docs)
    with pytest.raises(ValueError, match="rag.index"):
        open_index(s, changed)


def test_changed_chunking_or_embedding_changes_key(tmp_path):
    base = make_cfg(tmp_path)
    docs = load_documents(rag_settings(base)["docs_dir"])
    k0 = index_key(rag_settings(base), docs)
    assert index_key(rag_settings(make_cfg(tmp_path, chunking={"size": 400, "overlap": 50})), docs) != k0
    assert index_key(rag_settings(make_cfg(tmp_path, embedding={"model": "other"})), docs) != k0
    # k and generation do not affect the vectors: same index
    assert index_key(rag_settings(make_cfg(tmp_path, retrieval={"k": 9})), docs) == k0


def test_rebuild_same_config_replaces_index(setup):
    s, docs = setup
    p1 = build_index(s, docs, HashEmbedder())
    p2 = build_index(s, docs, HashEmbedder())
    assert p1 == p2 and p1.is_dir()
    assert not list(p1.parent.glob("*.tmp"))


def test_search_text_is_lexical_and_french_stemmed(setup):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    hits = open_index(s, docs).search_text("capitales de France", 3)
    assert hits and hits[0]["doc_id"] == "geo.md"
    assert {"id", "text", "start", "end", "score"} <= set(hits[0])


@pytest.mark.parametrize("q", ["", "la de", '"capitale', "(a OR b) AND:", "C++ -France", "capitale:*"])
def test_search_text_never_raises(setup, q):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    assert isinstance(open_index(s, docs).search_text(q, 3), list)


def test_search_text_n_larger_than_corpus(setup):
    s, docs = setup
    build_index(s, docs, HashEmbedder())
    index = open_index(s, docs)
    big = [p["id"] for p in index.search_text("France", 1000)]
    assert big and big == [p["id"] for p in index.search_text("France", 10)]
