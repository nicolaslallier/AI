import hashlib
import math
import re


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


class HashEmbedder:
    """Bag-of-words hashed into `dim` buckets, L2-normalized. Deterministic, no model."""

    def __init__(self, dim=256):
        self.dim = dim

    def _vec(self, text):
        v = [0.0] * self.dim
        for tok in re.findall(r"\w+", text.casefold()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)
