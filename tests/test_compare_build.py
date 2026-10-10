import pytest

import finetune.system as ft_system
import rag.system as rag_system
from evalkit.compare import build_systems
from fakes import HashEmbedder, ScriptedGenerator, make_cfg
from rag.index import build_index
from rag.ingest import load_documents


def setup(tmp_path, monkeypatch, index=True, **compare):
    cfg = make_cfg(tmp_path)
    cfg["compare"] = {"adapter": "runs/x/adapters", **compare}
    from evalkit.compare import compare_settings
    from rag.config import rag_settings

    cfg["compare"], cfg["rag"] = compare_settings(cfg), rag_settings(cfg)
    if index:
        build_index(cfg["rag"], load_documents(cfg["rag"]["docs_dir"]), HashEmbedder())
    made = []
    gens = {"": ScriptedGenerator("base [1]"), "runs/x/adapters": ScriptedGenerator("ft [1]")}

    def fake_make_generator(s):
        made.append((s["model"], s["adapter"]))
        return gens[s["adapter"]]

    monkeypatch.setattr(ft_system, "make_generator", fake_make_generator)
    monkeypatch.setattr(rag_system, "make_embedder", lambda s: HashEmbedder())
    return cfg, gens, made


def test_four_systems_share_two_generators(tmp_path, monkeypatch):
    cfg, gens, made = setup(tmp_path, monkeypatch)
    systems = build_systems(cfg)
    assert list(systems) == ["base", "base+rag", "ft", "ft+rag"]
    assert made == [("fake", ""), ("fake", "runs/x/adapters")]  # un chargement par modèle, pas par système
    q = "Quelle est la capitale de la France ?"
    assert systems["base"](q) == {"answer": "base [1]", "sources": []}
    assert systems["ft"](q)["answer"] == "ft [1]"
    out = systems["base+rag"](q)
    assert out["retrieved"][0] == "geo.md" and out["sources"] == ["geo.md"]
    assert systems["ft+rag"](q)["answer"] == "ft [1]"
    assert len(gens[""].calls) == 2 and len(gens["runs/x/adapters"].calls) == 2


def test_plain_systems_use_the_training_system_prompt(tmp_path, monkeypatch):
    cfg, gens, _ = setup(tmp_path, monkeypatch, systems=["base"], system_prompt="Sois bref.")
    build_systems(cfg)["base"]("Q ?")
    assert gens[""].calls[0] == [{"role": "system", "content": "Sois bref."}, {"role": "user", "content": "Q ?"}]


def test_only_what_is_needed_is_loaded(tmp_path, monkeypatch):
    cfg, _, made = setup(tmp_path, monkeypatch, index=False, systems=["base"])
    build_systems(cfg)  # pas d'index requis, pas d'adaptateur chargé
    assert made == [("fake", "")]


def test_stale_index_fails_before_any_generation(tmp_path, monkeypatch):
    cfg, _, made = setup(tmp_path, monkeypatch, index=False, systems=["base+rag"])
    with pytest.raises(ValueError, match="rag.index"):
        build_systems(cfg)
    assert made == []  # aucun générateur chargé
