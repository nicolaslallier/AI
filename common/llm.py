class Generator:
    """Enveloppe minimale de mlx-lm. Un adaptateur LoRA (M2) se passe via `adapter_path`."""

    def __init__(self, model, adapter_path=None):
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
