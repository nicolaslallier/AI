import finetune.system as ft_system
from common.jsonl import read_jsonl
from evalkit.harness import evaluate
from finetune.data import to_messages
from finetune.prepare import prepare
from ft_fakes import make_ft_cfg


class FormatGenerator:
    """Imite un modèle qui a appris le format : « Réponse : <capitale>. »"""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def generate(self, messages, max_tokens=400, temperature=0.0):
        self.calls.append((messages, max_tokens, temperature))
        return self.answers[messages[-1]["content"]]


def test_system_uses_the_training_prompt_and_feeds_the_harness(tmp_path, monkeypatch):
    cfg = make_ft_cfg(tmp_path, system_prompt="Réponds brièvement.", generation={"max_tokens": 50})
    prepare(cfg)
    qa = read_jsonl(tmp_path / "data" / "valid_eval.jsonl")
    gen = FormatGenerator({r["question"]: r["answer"] for r in qa})
    monkeypatch.setattr(ft_system, "make_generator", lambda s: gen)
    answer = ft_system.build(cfg)
    metrics, results = evaluate(answer, qa)
    assert metrics["accuracy"] == 1.0 and metrics["n"] == len(qa)
    assert gen.calls[0][0] == to_messages(qa[0]["question"], "Réponds brièvement.")
    assert gen.calls[0][1:] == (50, 0.0)
    assert results[0]["sources"] == []


def test_generator_receives_the_adapter_only_when_configured(tmp_path, monkeypatch):
    seen = []

    class Spy:
        def __init__(self, model, adapter_path=None):
            seen.append((model, adapter_path))

    monkeypatch.setattr("common.llm.Generator", Spy)
    from finetune.config import ft_settings

    ft_system.make_generator(ft_settings(make_ft_cfg(tmp_path)))
    ft_system.make_generator(ft_settings(make_ft_cfg(tmp_path, adapter="runs/x/adapters")))
    assert seen == [("fake-model", None), ("fake-model", "runs/x/adapters")]
