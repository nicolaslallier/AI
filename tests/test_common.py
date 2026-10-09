import pytest

from common.config import load_config
from common.jsonl import read_jsonl, read_qa, write_jsonl


def test_roundtrip_keeps_unicode(tmp_path):
    p = tmp_path / "sub" / "a.jsonl"
    write_jsonl(p, [{"q": "Où ?"}])
    assert "Où" in p.read_text(encoding="utf-8")
    assert read_jsonl(p) == [{"q": "Où ?"}]


def test_blank_lines_are_skipped(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a":1}\n\n{"a":2}\n\n', encoding="utf-8")
    assert read_jsonl(p) == [{"a": 1}, {"a": 2}]


def test_bad_line_reports_file_and_line(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_text('{"a":1}\n{oops\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"a\.jsonl:2"):
        read_jsonl(p)


def _qa(tmp_path, rows):
    p = tmp_path / "qa.jsonl"
    write_jsonl(p, rows)
    return p


GOOD = {"id": "1", "question": "q", "answer": "a", "sources": ["s.md"]}


def test_read_qa_ok(tmp_path):
    assert read_qa(_qa(tmp_path, [GOOD])) == [GOOD]


def test_read_qa_rejects_missing_key(tmp_path):
    bad = {k: v for k, v in GOOD.items() if k != "sources"}
    with pytest.raises(ValueError, match="sources"):
        read_qa(_qa(tmp_path, [bad]))


def test_read_qa_rejects_empty_answer(tmp_path):
    with pytest.raises(ValueError, match="answer"):
        read_qa(_qa(tmp_path, [{**GOOD, "answer": "  "}]))


def test_read_qa_rejects_duplicate_ids(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        read_qa(_qa(tmp_path, [GOOD, GOOD]))


def test_config_ok(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("name: demo\nseed: 3\nextra: 1\n", encoding="utf-8")
    assert load_config(p) == {"name": "demo", "seed": 3, "extra": 1}


@pytest.mark.parametrize("body", ["seed: 1\n", "name: x\n", "name: a/b\nseed: 1\n", "- 1\n"])
def test_config_rejects_invalid(tmp_path, body):
    p = tmp_path / "c.yaml"
    p.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)


@pytest.mark.parametrize("row", ["[1,2]", "42", '{"id":[1],"question":"q","answer":"a","sources":[]}'])
def test_read_qa_rejects_odd_rows(tmp_path, row):
    p = tmp_path / "qa.jsonl"
    p.write_text(row + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_qa(p)


def test_config_rejects_bool_seed(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("name: x\nseed: true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(p)
