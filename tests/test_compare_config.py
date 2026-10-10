import pytest

from evalkit.compare import SYSTEMS, compare_settings, load_compare_config
from fakes import make_cfg
from ft_fakes import write_cfg


def cfg_with(tmp_path, **compare):
    cfg = make_cfg(tmp_path)
    cfg.update(eval_set="data/examples/compare_eval.jsonl", compare=compare)
    return cfg


def test_defaults(tmp_path):
    c = compare_settings(cfg_with(tmp_path, adapter="runs/x/adapters"))
    assert c["systems"] == list(SYSTEMS) and c["min_gap"] == 2 and c["train_file"] == ""


@pytest.mark.parametrize(
    "compare, msg",
    [
        ({"systems": ["base", "gpt"], "adapter": "a"}, "compare.systems"),
        ({"systems": ["base", "base"]}, "compare.systems"),
        ({"systems": []}, "compare.systems"),
        ({"systems": ["ft"]}, "compare.adapter"),
        ({"systems": ["ft+rag"], "adapter": ""}, "compare.adapter"),
        ({"min_gap": 0, "adapter": "a"}, "compare.min_gap"),
        ({"adaptor": "a"}, "unknown key"),
    ],
)
def test_invalid(tmp_path, compare, msg):
    with pytest.raises(ValueError, match=msg):
        compare_settings(cfg_with(tmp_path, **compare))


def test_base_only_needs_no_adapter(tmp_path):
    assert compare_settings(cfg_with(tmp_path, systems=["base", "base+rag"]))["adapter"] == ""


def test_load_prefixes_path_and_requires_eval_set(tmp_path):
    cfg = cfg_with(tmp_path, systems=["ft"])
    path = write_cfg(tmp_path, cfg)
    with pytest.raises(ValueError, match=r"cfg\.yaml.*compare\.adapter"):
        load_compare_config(path)
    del cfg["eval_set"]
    cfg["compare"] = {"systems": ["base"]}
    with pytest.raises(ValueError, match="eval_set"):
        load_compare_config(write_cfg(tmp_path, cfg))
