import argparse
import re
import statistics
from pathlib import Path

from rag.chunk import chunk_document
from rag.config import load_rag_config

TEXT_EXTS = {".md", ".markdown", ".txt", ".py", ".js", ".ts", ".java", ".go", ".rs", ".c", ".cpp", ".sh", ".sql"}


def clean(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text)


def load_documents(docs_dir):
    root = Path(docs_dir)
    if not root.is_dir():
        raise ValueError(f"docs_dir not found: {docs_dir} (put your documents there)")
    docs = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_EXTS and not any(x.startswith(".") for x in p.relative_to(root).parts):
            try:
                text = p.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError as e:
                raise ValueError(f"{p}: not valid UTF-8 ({e.reason})") from e
            docs.append({"doc_id": p.relative_to(root).as_posix(), "text": clean(text)})
    if not docs:
        raise ValueError(f"no supported documents in {docs_dir} (extensions: {sorted(TEXT_EXTS)})")
    return docs


def build_chunks(docs, size, overlap):
    return [c for d in docs for c in chunk_document(d["doc_id"], d["text"], size, overlap)]


def main(argv):
    ap = argparse.ArgumentParser(prog="rag.ingest", description="Load and chunk documents (preview).")
    ap.add_argument("config")
    args = ap.parse_args(argv)
    s = load_rag_config(args.config)["rag"]
    docs = load_documents(s["docs_dir"])
    chunks = build_chunks(docs, s["chunking"]["size"], s["chunking"]["overlap"])
    if not chunks:
        raise ValueError(f"{s['docs_dir']}: no non-empty text to chunk")
    median = statistics.median(len(c["text"]) for c in chunks)
    print(f"{len(docs)} documents, {len(chunks)} chunks, median {median:.0f} chars")
    print(f"Next: uv run python -m rag.index {args.config}")


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
