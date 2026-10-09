import pytest

from rag.chunk import chunk_document, split_spans


def test_short_text_is_one_chunk():
    assert split_spans("bonjour", 800, 100) == [(0, 7)]


def test_empty_text_has_no_chunks():
    assert split_spans("", 800, 100) == []
    assert chunk_document("a.md", "", 800, 100) == []


def test_no_separator_terminates_and_respects_size():
    text = "x" * 5000
    spans = split_spans(text, 800, 100)
    assert all(0 < e - s <= 800 for s, e in spans)
    assert spans[0][0] == 0 and spans[-1][1] == 5000
    # consecutive spans overlap by exactly `overlap` here (no separators to cut on)
    assert all(spans[i + 1][0] == spans[i][1] - 100 for i in range(len(spans) - 1))


def test_spans_cover_text_without_gaps():
    text = ("Un paragraphe assez long. " * 10 + "\n\n") * 8
    spans = split_spans(text, 200, 30)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(spans[i + 1][0] <= spans[i][1] for i in range(len(spans) - 1))
    assert all(e - s <= 200 for s, e in spans)


def test_prefers_paragraph_boundary():
    text = "a" * 60 + "\n\n" + "b" * 60
    (s0, e0), _ = split_spans(text, 100, 0)
    assert text[s0:e0] == "a" * 60 + "\n\n"


def test_heading_starts_next_chunk():
    text = "intro " * 12 + "\n## Titre\ncorps"
    chunks = chunk_document("a.md", text, 80, 0)
    assert any(c["text"].startswith("## Titre") for c in chunks)


def test_ids_offsets_and_text_agree():
    text = "mot " * 400
    chunks = chunk_document("notes/lora.md", text, 300, 50)
    assert [c["id"] for c in chunks] == [f"notes/lora.md#{i}" for i in range(len(chunks))]
    assert all(c["doc_id"] == "notes/lora.md" for c in chunks)
    assert all(text[c["start"] : c["end"]] == c["text"] for c in chunks)


def test_ids_are_stable_across_calls():
    text = "phrase. " * 300
    assert chunk_document("a.md", text, 200, 20) == chunk_document("a.md", text, 200, 20)


def test_whitespace_only_chunks_are_dropped():
    chunks = chunk_document("a.md", "texte" + " " * 500, 100, 0)
    assert chunks and all(c["text"].strip() for c in chunks)
    assert [c["id"] for c in chunks] == [f"a.md#{i}" for i in range(len(chunks))]


def test_overlap_must_be_smaller_than_size():
    with pytest.raises(ValueError):
        split_spans("abc", 10, 10)
