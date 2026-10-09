def make_cfg(tmp_path, **rag_overrides):
    rag = {
        "docs_dir": "data/examples/docs",
        "index_dir": str(tmp_path / "index"),
        "chunking": {"size": 800, "overlap": 100},
        "embedding": {"model": "hash"},
        "retrieval": {"k": 2},
        "generation": {"model": "fake"},
    }
    rag.update(rag_overrides)
    return {"name": "t", "seed": 0, "rag": rag}
