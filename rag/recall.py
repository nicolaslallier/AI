import argparse

from common.jsonl import read_qa
from evalkit.metrics import source_hit
from rag.config import load_rag_config
from rag.index import open_index
from rag.ingest import load_documents
from rag.retrieve import CrossEncoderReranker, Retriever


def recall_table(qa, retrievers):
    rows = [r for r in qa if r["sources"]]
    return {
        name: (sum(source_hit([p["doc_id"] for p in ret(r["question"])], r["sources"]) for r in rows) / len(rows)
               if rows else None)
        for name, ret in retrievers.items()
    }


def main(argv):
    from rag.system import make_embedder

    ap = argparse.ArgumentParser(prog="rag.recall", description="recall@k per retrieval mode, no LLM loaded.")
    ap.add_argument("config")
    args = ap.parse_args(argv)
    cfg = load_rag_config(args.config)
    s = cfg["rag"]
    r = s["retrieval"]
    index, emb = open_index(s, load_documents(s["docs_dir"])), make_embedder(s)
    reranker = CrossEncoderReranker(r["rerank"]) if r["rerank"] else None
    retrievers = {m: Retriever(index, emb, m, r["k"], r["candidates"]) for m in ("dense", "hybrid")}
    if reranker:
        retrievers |= {f"{m}+rerank": Retriever(index, emb, m, r["k"], r["candidates"], reranker) for m in ("dense", "hybrid")}
    qa = read_qa(cfg["eval_set"])
    print(f"| mode | recall@{r['k']} (n={sum(bool(q['sources']) for q in qa)}) |\n|---|---|")
    for name, v in recall_table(qa, retrievers).items():
        print(f"| {name} | {'—' if v is None else f'{v:.2f}'.replace('.', ',')} |")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
