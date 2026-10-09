import json

import pytest

from common.jsonl import read_jsonl, write_jsonl
from finetune.data import to_messages
from finetune.prepare import main, prepare, split_of
from ft_fakes import make_ft_cfg, write_cfg


def test_prepare_splits_example_source_without_overlap(tmp_path):
    counts = prepare(make_ft_cfg(tmp_path))
    assert sum(counts.values()) == 30 and all(counts.values())
    ids = {n: {r["id"] for r in read_jsonl(tmp_path / "data" / f"{n}_eval.jsonl")} for n in ("valid", "test")}
    assert not ids["valid"] & ids["test"]
    assert len(read_jsonl(tmp_path / "data" / "train.jsonl")) == counts["train"]


def test_chat_format_matches_inference_prompt(tmp_path):
    prepare(make_ft_cfg(tmp_path, system_prompt="Réponds brièvement."))
    row = read_jsonl(tmp_path / "data" / "valid.jsonl")[0]["messages"]
    assert [m["role"] for m in row] == ["system", "user", "assistant"]
    assert row[:2] == to_messages(row[1]["content"], "Réponds brièvement.")
    assert to_messages("q") == [{"role": "user", "content": "q"}]


def test_split_is_stable_when_rows_are_added():
    before = {i: split_of(f"id{i}", 0, 0.15, 0.15) for i in range(200)}
    after = {i: split_of(f"id{i}", 0, 0.15, 0.15) for i in range(400)}
    assert all(before[i] == after[i] for i in before)
    assert split_of("id1", 0, 0.15, 0.15) == split_of("id1", 0, 0.15, 0.15)
    assert {split_of(f"id{i}", 0, 0.15, 0.15) for i in range(200)} == {"train", "valid", "test"}


def test_seed_changes_the_split():
    a = [split_of(f"id{i}", 0, 0.15, 0.15) for i in range(100)]
    b = [split_of(f"id{i}", 1, 0.15, 0.15) for i in range(100)]
    assert a != b


def test_too_few_rows_gives_a_clear_error(tmp_path):
    src = tmp_path / "tiny.jsonl"
    write_jsonl(src, [{"id": "a", "question": "q", "answer": "r", "sources": []}])
    with pytest.raises(ValueError, match="empty split"):
        prepare(make_ft_cfg(tmp_path, source=str(src)))


def test_source_errors_name_the_file(tmp_path):
    src = tmp_path / "bad.jsonl"
    src.write_text(json.dumps({"id": "a", "question": "q"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing key 'answer'"):
        prepare(make_ft_cfg(tmp_path, source=str(src)))


def test_cli_prints_counts_and_next_step(tmp_path, capsys):
    path = write_cfg(tmp_path, make_ft_cfg(tmp_path))
    main([str(path)])
    out = capsys.readouterr().out
    assert "train" in out and "finetune.train" in out


def test_split_depends_on_split_seed_not_experiment_seed(tmp_path):
    def ids(seed, split_seed, sub):
        cfg = make_ft_cfg(tmp_path / sub, split={"seed": split_seed})
        cfg["seed"] = seed
        prepare(cfg)
        return [r["id"] for r in read_jsonl(tmp_path / sub / "data" / "test_eval.jsonl")]

    assert ids(0, 0, "a") == ids(7, 0, "b")
    assert ids(0, 0, "a") != ids(0, 1, "c")
