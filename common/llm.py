import json
from pathlib import Path


def check_adapter(model, adapter_path):
    """Un adaptateur LoRA n'est valide que pour le modèle de base qui l'a produit (TRD §6.3)."""
    cfg_file = Path(adapter_path) / "adapter_config.json"
    if not cfg_file.is_file():
        raise ValueError(f"{adapter_path}: no adapter_config.json (is this an adapter directory?)")
    trained_on = json.loads(cfg_file.read_text(encoding="utf-8")).get("model")
    if trained_on != model:
        raise ValueError(f"adapter {adapter_path} was trained on {trained_on!r}, not {model!r}")


class Generator:
    """Enveloppe minimale de mlx-lm. Un adaptateur LoRA (M2) se passe via `adapter_path`."""

    def __init__(self, model, adapter_path=None):
        if adapter_path:
            check_adapter(model, adapter_path)
        from mlx_lm import load

        self.model, self.tokenizer = load(model, adapter_path=adapter_path)

    def generate(self, messages, max_tokens=400, temperature=0.0):
        from mlx_lm import generate
        from mlx_lm.sample_utils import make_sampler

        prompt = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        return generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=make_sampler(temp=temperature),
            verbose=False,
        )
