import pytest

from fakes import make_cfg
from rag.config import load_rag_config, rag_settings


def test_defaults_are_applied(tmp_path):
    s = rag_settings(make_cfg(tmp_path))
    assert s["embedding"]["batch_size"] == 16
    assert s["embedding"]["query_prefix"] == ""
    assert s["generation"]["temperature"] == 0.0
    assert s["retrieval"]["k"] == 2


def test_example_config_loads():
    cfg = load_rag_config("configs/rag-example.yaml")
    assert cfg["rag"]["chunking"] == {"size": 800, "overlap": 100}


def test_unknown_key_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg["rag"]["retreival"] = {"k": 3}
    with pytest.raises(ValueError, match="retreival"):
        rag_settings(cfg)


def test_unknown_nested_key_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="kk"):
        rag_settings(make_cfg(tmp_path, retrieval={"kk": 3}))


def test_missing_required_key(tmp_path):
    cfg = make_cfg(tmp_path)
    del cfg["rag"]["docs_dir"]
    with pytest.raises(ValueError, match="docs_dir"):
        rag_settings(cfg)


def test_missing_rag_section():
    with pytest.raises(ValueError, match="rag"):
        rag_settings({"name": "t", "seed": 0})


@pytest.mark.parametrize(
    "chunking", [{"size": 100, "overlap": 100}, {"size": 0, "overlap": 0}, {"size": 100, "overlap": -1}]
)
def test_bad_chunking(tmp_path, chunking):
    with pytest.raises(ValueError, match="chunking"):
        rag_settings(make_cfg(tmp_path, chunking=chunking))


@pytest.mark.parametrize("k", [0, -1, True, "5"])
def test_bad_k(tmp_path, k):
    with pytest.raises(ValueError, match="retrieval.k"):
        rag_settings(make_cfg(tmp_path, retrieval={"k": k}))


def test_retrieval_defaults_keep_m1_behaviour(tmp_path):
    r = rag_settings(make_cfg(tmp_path))["retrieval"]
    assert r == {"mode": "dense", "k": 2, "candidates": 20, "rerank": ""}


@pytest.mark.parametrize(
    "retrieval, msg",
    [
        ({"mode": "bm25"}, "rag.retrieval.mode"),
        ({"k": 5, "candidates": 3}, "candidates"),
        ({"candidates": 0}, "candidates"),
        ({"rerank": 3}, "rag.retrieval.rerank"),
    ],
)
def test_retrieval_rejects_bad_values(tmp_path, retrieval, msg):
    with pytest.raises(ValueError, match=msg):
        rag_settings(make_cfg(tmp_path, retrieval=retrieval))


def test_hybrid_and_rerank_are_accepted(tmp_path):
    r = rag_settings(make_cfg(tmp_path, retrieval={"k": 3, "mode": "hybrid", "rerank": "some/model"}))["retrieval"]
    assert (r["mode"], r["rerank"], r["candidates"]) == ("hybrid", "some/model", 20)
