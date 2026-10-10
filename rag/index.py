import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path

import lancedb

from rag.config import load_rag_config
from rag.ingest import build_chunks, load_documents

TABLE = "chunks"


def index_key(settings, docs):
    e = settings["embedding"]
    payload = {
        "chunking": settings["chunking"],
        "embedding": {k: e[k] for k in ("model", "query_prefix", "passage_prefix")},
        "docs": [[d["doc_id"], hashlib.sha256(d["text"].encode()).hexdigest()] for d in docs],
        "fts": "french-v1",  # changer si les paramètres FTS changent
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]


def _path(settings, docs):
    return Path(settings["index_dir"]) / index_key(settings, docs)


def build_index(settings, docs, embedder):
    c = settings["chunking"]
    chunks = build_chunks(docs, c["size"], c["overlap"])
    if not chunks:
        raise ValueError("no chunks to index (all documents are empty)")
    vectors = embedder.embed_documents([ch["text"] for ch in chunks])
    path = _path(settings, docs)
    tmp = path.with_name(path.name + ".tmp")  # un index à moitié écrit n'est jamais servi
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    table = lancedb.connect(str(tmp)).create_table(TABLE, data=[{**ch, "vector": v} for ch, v in zip(chunks, vectors)])
    table.create_fts_index("text", use_tantivy=False, language="French", replace=True)
    shutil.rmtree(path, ignore_errors=True)
    tmp.rename(path)
    return path


_FIELDS = ("id", "doc_id", "text", "start", "end")


class Index:
    def __init__(self, path):
        self._table = lancedb.connect(str(path)).open_table(TABLE)

    def search(self, query_vec, k):
        rows = self._table.search(query_vec).metric("cosine").limit(k).to_list()
        return [{**{f: r[f] for f in _FIELDS}, "score": 1.0 - r["_distance"]} for r in rows]

    def search_text(self, query, n):
        rows = self._table.search(query, query_type="fts").limit(n).to_list()
        return [{**{f: r[f] for f in _FIELDS}, "score": r["_score"]} for r in rows]


def open_index(settings, docs):
    path = _path(settings, docs)
    if not path.is_dir():
        raise ValueError(
            "no index for the current documents/config (documents or chunking/embedding changed?): "
            "run `uv run python -m rag.index CONFIG`"
        )
    return Index(path)


def main(argv):
    from rag.embed import make_embedder

    ap = argparse.ArgumentParser(prog="rag.index", description="Embed chunks and write the vector index.")
    ap.add_argument("config")
    args = ap.parse_args(argv)
    s = load_rag_config(args.config)["rag"]
    docs = load_documents(s["docs_dir"])
    t0 = time.time()
    path = build_index(s, docs, make_embedder(s))
    n = len(build_chunks(docs, s["chunking"]["size"], s["chunking"]["overlap"]))
    print(f"index written: {path} ({n} chunks) in {time.time() - t0:.0f}s")
    print(f'Next: uv run python -m rag.ask {args.config} "..."')


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
