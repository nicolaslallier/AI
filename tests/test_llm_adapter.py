import json

import pytest

from common.llm import Generator, check_adapter


def make_adapter(tmp_path, model="base-a"):
    d = tmp_path / "adapters"
    d.mkdir()
    (d / "adapter_config.json").write_text(json.dumps({"model": model}), encoding="utf-8")
    return d


def test_matching_adapter_passes(tmp_path):
    check_adapter("base-a", make_adapter(tmp_path))


def test_adapter_for_another_base_model_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="trained on 'base-a', not 'base-b'"):
        check_adapter("base-b", make_adapter(tmp_path))


def test_missing_or_wrong_directory_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="no adapter_config.json"):
        check_adapter("base-a", tmp_path / "nowhere")


def test_generator_checks_before_loading_any_weights(tmp_path):
    # Si la vérification n'avait pas lieu en premier, mlx_lm tenterait de télécharger « base-b ».
    with pytest.raises(ValueError, match="trained on"):
        Generator("base-b", adapter_path=make_adapter(tmp_path))
