from finetune.config import ft_settings
from finetune.data import to_messages


def make_generator(s):
    from common.llm import Generator

    return Generator(s["model"], adapter_path=s["adapter"] or None)


def build(cfg):
    import mlx.core as mx

    mx.random.seed(cfg["seed"])
    s = ft_settings(cfg)
    gen, g = make_generator(s), s["generation"]

    def answer(question):
        text = gen.generate(
            to_messages(question, s["system_prompt"]), max_tokens=g["max_tokens"], temperature=g["temperature"]
        )
        return {"answer": text, "sources": []}

    return answer
