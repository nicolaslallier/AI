import math

from common.jsonl import write_jsonl
from finetune.curves import plot, read_log, summarize


def tr(step, loss):
    return {"step": step, "train_loss": loss, "it_per_sec": 2.0, "peak_mem_gb": 1.5}


def va(step, loss):
    return {"step": step, "val_loss": loss}


def test_summary_of_a_healthy_run():
    log = [va(0, 4.0), tr(10, 2.0), va(20, 1.0), tr(30, 0.8), va(40, 0.9)]
    s = summarize(log)
    assert s["first_val_loss"] == 4.0 and s["best_val_loss"] == 0.9 and s["best_val_step"] == 40
    assert s["final_val_loss"] == 0.9 and s["final_train_loss"] == 0.8
    assert s["peak_mem_gb"] == 1.5 and s["it_per_sec"] == 2.0 and s["n_val_points"] == 3
    assert s["val_rising"] is False


def test_rising_validation_loss_is_flagged():
    assert summarize([va(0, 4.0), va(20, 1.0), va(40, 1.5)])["val_rising"] is True


def test_log_without_validation_or_empty_does_not_crash():
    assert summarize([tr(10, 2.0)])["n_val_points"] == 0
    assert "best_val_loss" not in summarize([tr(10, 2.0)])
    assert summarize([]) == {"n_val_points": 0}


def test_nan_validation_loss_is_ignored():
    s = summarize([va(0, math.nan), va(20, 1.0)])
    assert s["first_val_loss"] == 1.0 and s["n_val_points"] == 1


def test_plot_writes_a_png_and_read_log_tolerates_missing_file(tmp_path):
    log = [va(0, 4.0), tr(10, 2.0), va(20, 1.0)]
    plot(log, tmp_path / "curves.png")
    assert (tmp_path / "curves.png").stat().st_size > 0
    plot([], tmp_path / "empty.png")
    write_jsonl(tmp_path / "log.jsonl", log)
    assert read_log(tmp_path / "log.jsonl") == log
    assert read_log(tmp_path / "nope.jsonl") == []
