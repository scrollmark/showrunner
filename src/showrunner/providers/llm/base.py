"""Abstract LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Generate text from prompts."""

    @abstractmethod
    def generate(self, *, system: str, prompt: str, max_tokens: int = 4096) -> str:
        """Generate text given a system prompt and user prompt."""

    @abstractmethod
    def generate_json(self, *, system: str, prompt: str, max_tokens: int = 4096) -> dict:
        """Generate structured JSON output."""
