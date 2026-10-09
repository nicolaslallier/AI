import pytest

from common.config import merge_section
from finetune.config import ft_settings, load_ft_config
from ft_fakes import make_ft_cfg, write_cfg


def test_merge_section_fills_defaults_and_rejects_unknown_keys():
    schema = {"a": None, "b": {"c": 1}}
    assert merge_section(schema, {"a": 5}, "x") == {"a": 5, "b": {"c": 1}}
    with pytest.raises(ValueError, match=r"unknown key\(s\) in 'x.b': \['cc'\]"):
        merge_section(schema, {"a": 5, "b": {"cc": 2}}, "x")
    with pytest.raises(ValueError, match="'x.a' is required"):
        merge_section(schema, {}, "x")


def test_example_config_loads_with_defaults():
    cfg = load_ft_config("configs/ft-example.yaml")
    s = cfg["finetune"]
    assert s["lora"]["rank"] == 8 and s["train"]["iters"] == 100 and s["adapter"] == ""


def test_typo_in_section_fails_with_the_key_name(tmp_path):
    cfg = make_ft_cfg(tmp_path, lroa={"rank": 4})
    with pytest.raises(ValueError, match="lroa"):
        ft_settings(cfg)
    path = write_cfg(tmp_path, cfg)
    with pytest.raises(ValueError, match=str(path)):
        load_ft_config(path)


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"train": {"iters": 0}}, "finetune.train.iters"),
        ({"train": {"learning_rate": 0}}, "learning_rate"),
        ({"lora": {"rank": True}}, "finetune.lora.rank"),
        ({"split": {"valid": 0.6, "test": 0.5}}, "finetune.split"),
        ({"split": {"valid": 0, "test": 0.2}}, "finetune.split"),
        ({"generation": {"temperature": -1}}, "temperature"),
        ({"model": ""}, "finetune.model"),
    ],
)
def test_invalid_values_are_rejected(tmp_path, overrides, message):
    with pytest.raises(ValueError, match=message):
        ft_settings(make_ft_cfg(tmp_path, **overrides))


def test_missing_required_key(tmp_path):
    cfg = make_ft_cfg(tmp_path)
    del cfg["finetune"]["model"]
    with pytest.raises(ValueError, match="finetune.model' is required"):
        ft_settings(cfg)
