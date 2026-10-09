import pytest

from rag.ingest import build_chunks, load_documents, main


def test_load_example_docs():
    docs = load_documents("data/examples/docs")
    assert [d["doc_id"] for d in docs] == ["geo.md", "lora.md", "rag.md"]
    assert "Paris" in docs[0]["text"]


def test_nested_files_use_posix_relative_ids(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("alpha", encoding="utf-8")
    (tmp_path / "ignored.png").write_bytes(b"\x89PNG")
    assert [d["doc_id"] for d in load_documents(tmp_path)] == ["notes/a.md"]


def test_cleaning_normalizes_newlines_and_blank_runs(tmp_path):
    (tmp_path / "a.txt").write_text("l1  \r\n\r\n\r\n\r\nl2\t\n", encoding="utf-8")
    assert load_documents(tmp_path)[0]["text"] == "l1\n\nl2\n"


def test_missing_dir_names_the_dir(tmp_path):
    with pytest.raises(ValueError, match="nope"):
        load_documents(tmp_path / "nope")


def test_empty_dir_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="no supported documents"):
        load_documents(tmp_path)


def test_non_utf8_file_names_the_file(tmp_path):
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ValueError, match="bad.md"):
        load_documents(tmp_path)


def test_build_chunks_concatenates_documents():
    docs = [{"doc_id": "a.md", "text": "un"}, {"doc_id": "b.md", "text": "deux"}]
    assert [c["id"] for c in build_chunks(docs, 800, 100)] == ["a.md#0", "b.md#0"]


def test_cli_prints_stats(capsys):
    main(["configs/rag-example.yaml"])
    out = capsys.readouterr().out
    assert "3 documents" in out and "3 chunks" in out


def test_hidden_dirs_are_skipped(tmp_path):
    for d, name, data in [(".obsidian", "x.md", b"x"), (".trash", "y.md", b"y"), (".git", "z.txt", b"\xff\xfe\x00")]:
        (tmp_path / d).mkdir()
        (tmp_path / d / name).write_bytes(data)
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    assert [d["doc_id"] for d in load_documents(tmp_path)] == ["a.md"]


def test_bom_is_stripped(tmp_path):
    (tmp_path / "a.md").write_bytes(b"\xef\xbb\xbfbonjour")
    assert load_documents(tmp_path)[0]["text"] == "bonjour"


def test_cli_rejects_docs_without_text(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "blank.md").write_text("  \n\n", encoding="utf-8")
    cfg = tmp_path / "c.yaml"
    cfg.write_text(
        f"name: t\nseed: 0\nrag:\n  docs_dir: {docs}\n  embedding: {{model: m}}\n  generation: {{model: g}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no non-empty text"):
        main([str(cfg)])
