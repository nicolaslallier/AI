import yaml

import rag.system as rs
from evalkit import run
from fakes import HashEmbedder, ScriptedGenerator, make_cfg
from rag.config import rag_settings
from rag.index import build_index
from rag.ingest import load_documents


def prepare(tmp_path, monkeypatch, reply="D'après les documents [1]."):
    cfg = make_cfg(tmp_path)
    cfg.update(eval_set="data/examples/rag_eval.jsonl", system="rag.system:build", runs_dir=str(tmp_path / "runs"))
    s = rag_settings(cfg)
    build_index(s, load_documents(s["docs_dir"]), HashEmbedder())
    gen = ScriptedGenerator(reply)
    monkeypatch.setattr(rs, "make_embedder", lambda settings: HashEmbedder())
    monkeypatch.setattr(rs, "make_generator", lambda settings: gen)
    return cfg, gen


def test_answer_contract(tmp_path, monkeypatch):
    cfg, gen = prepare(tmp_path, monkeypatch)
    out = rs.build(cfg)("Quelle est la capitale de la France ?")
    assert out["retrieved"][0] == "geo.md" and len(out["retrieved"]) == 2
    assert out["sources"] == ["geo.md"] and out["cited"] == [1]
    assert (out["citations"], out["invalid_citations"]) == (1, 0)
    assert out["passages"][0]["score"] >= out["passages"][1]["score"]
    assert "Paris" in gen.calls[0][1]["content"]


def test_invalid_and_missing_citations(tmp_path, monkeypatch):
    cfg, _ = prepare(tmp_path, monkeypatch, reply="Selon [9] et [1][1].")
    out = rs.build(cfg)("Quelle est la capitale de la France ?")
    assert out["sources"] == ["geo.md"]  # no duplicate
    assert (out["citations"], out["invalid_citations"]) == (3, 1)

    cfg, _ = prepare(tmp_path, monkeypatch, reply="Je n'ai pas trouvé d'information dans les documents indexés.")
    out = rs.build(cfg)("Quelle est la capitale de la France ?")
    assert out["sources"] == [] and out["citations"] == 0


def test_stale_index_fails_with_command(tmp_path, monkeypatch):
    cfg, _ = prepare(tmp_path, monkeypatch)
    cfg["rag"]["chunking"] = {"size": 400, "overlap": 50}
    try:
        rs.build(cfg)
    except ValueError as e:
        assert "rag.index" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_end_to_end_through_evalkit(tmp_path, monkeypatch):
    cfg, _ = prepare(tmp_path, monkeypatch)
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    metrics = run.main([str(path)])
    assert metrics["n"] == 3
    assert metrics["recall_at_k"] == 1.0
    assert metrics["citation_validity"] == 1.0
    run_dir = next((tmp_path / "runs").iterdir())
    assert {"config.yaml", "metrics.json", "outputs.jsonl"} <= {p.name for p in run_dir.iterdir()}


def test_build_seeds_mlx(tmp_path, monkeypatch):
    import mlx.core as mx

    cfg, _ = prepare(tmp_path, monkeypatch)
    cfg["seed"] = 7
    seen = []
    monkeypatch.setattr(mx.random, "seed", seen.append)
    rs.build(cfg)
    assert seen == [7]


def test_hybrid_rerank_system_keeps_answer_contract(tmp_path, monkeypatch):
    cfg, _ = prepare(tmp_path, monkeypatch)
    cfg["rag"]["retrieval"] = {"k": 2, "mode": "hybrid", "rerank": "fake"}
    s = rag_settings(cfg)
    build_index(s, load_documents(s["docs_dir"]), HashEmbedder())
    from fakes import OverlapReranker
    monkeypatch.setattr("rag.retrieve.CrossEncoderReranker", lambda model: OverlapReranker())
    out = rs.build(cfg)("Quelle est la capitale de la France ?")
    assert len(out["retrieved"]) == 2 and out["sources"] == ["geo.md"]
