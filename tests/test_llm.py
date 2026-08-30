"""Tests for :mod:`mllab.llm`.

The network call in ``chat`` is mocked so the suite runs offline.
"""

from __future__ import annotations

import sys

import pytest

from mllab.llm import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMServer,
    chat,
    make_server,
    seed_everything,
)


def test_seed_everything_is_deterministic() -> None:
    import numpy as np

    seed_everything(7)
    first = np.random.random(3)
    seed_everything(7)
    second = np.random.random(3)
    np.testing.assert_array_equal(first, second)


def test_defaults_match_ollama_target() -> None:
    srv = LLMServer()
    assert srv.base_url == DEFAULT_BASE_URL
    assert srv.model == DEFAULT_MODEL
    assert srv.model == "ollama-remote/qwen3.8:27b-mlx"


def test_make_server_rejects_typos() -> None:
    with pytest.raises(TypeError):
        make_server(max_tokes=1)  # typo -> TypeError from dataclass __init__


def test_make_server_overrides_apply() -> None:
    srv = make_server(
        base_url="http://localhost:11434/v1", model="qwen3.8:27b-mlx", temperature=0.7
    )
    assert srv.base_url == "http://localhost:11434/v1"
    assert srv.model == "qwen3.8:27b-mlx"
    assert srv.temperature == 0.7


def test_chat_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    # Inject a fake ``openai`` module so ``LLMServer.client()`` builds a stub.
    class _Choice:
        class _Msg:
            def __init__(self, content: str) -> None:
                self.content = content

        def __init__(self, content: str) -> None:
            self.message = _Choice._Msg(content)

    class _Completions:
        def create(self, **_kwargs: object):
            class _Resp:
                choices = [_Choice("hello")]

            return _Resp()

    class _Chat:
        completions = _Completions()

    class _OpenAI:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.chat = _Chat()

    fake_module = type(sys)("")
    fake_module.OpenAI = _OpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_module)

    out = chat(LLMServer(model="any"), "you are helpful", "hi")
    assert out == "hello"
