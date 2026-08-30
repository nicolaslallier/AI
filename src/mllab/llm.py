"""LLM inference over OpenAI-compatible endpoints.

Targets Ollama (or any OpenAI-compatible server). The default ``base_url``
points at a LAN Ollama instance; override it via ``LLMServer``.

This module exposes *client construction and configuration* only. The network
call happens in ``chat`` (the I/O edge). Unit tests exercise the config path
without any network.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from openai import OpenAI

DEFAULT_MODEL: Final[str] = "ollama-remote/qwen3.8:27b-mlx"
DEFAULT_BASE_URL: Final[str] = "http://192.168.2.40:11434/v1"

__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_BASE_URL",
    "LLMServer",
    "make_server",
    "chat",
    "seed_everything",
]


@dataclass(frozen=True)
class LLMServer:
    """Connection settings for an OpenAI-compatible chat endpoint."""

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.0
    max_tokens: int = 1024
    api_key: str = "ollama"  # Ollama ignores the key but the SDK requires one.
    timeout: float = 120.0

    def client(self) -> OpenAI:
        """Build the underlying SDK client.

        Imported lazily so that config-only usage (tests, CLI plumbing) does not
        require the ``openai`` package at import time.
        """
        from openai import OpenAI

        return OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=self.timeout)


def make_server(
    *, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL, **overrides: object
) -> LLMServer:
    """Construct an ``LLMServer`` from keyword overrides.

    Unknown keys raise ``TypeError`` (``LLMServer.__init__``), preventing typos
    like ``max_tokes`` from silently vanishing.
    """
    return LLMServer(base_url=base_url, model=model, **overrides)  # type: ignore[arg-type]


def chat(server: LLMServer, system: str, user: str) -> str:
    """Send one user turn and return the assistant text.

    This is the network edge: it performs the request and returns text. It is
    intentionally kept out of any training/evaluation logic so the rest of the
    package stays pure and testable offline.
    """
    client = server.client()
    resp = client.chat.completions.create(
        model=server.model,
        temperature=server.temperature,
        max_tokens=server.max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    choices = resp.choices
    content = choices[0].message.content if choices else None
    return content or ""


def seed_everything(seed: int = 0) -> None:
    """Seed numpy and random for reproducibility.

    Idempotent and safe to call at the top of a training run.
    """
    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
