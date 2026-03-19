"""Anthropic (Claude) LLM provider."""

from __future__ import annotations

import json
import re

import anthropic

from showrunner.providers.llm.base import LLMProvider


class AnthropicLLMProvider(LLMProvider):
    """Claude-powered LLM provider."""

    def __init__(self, model: str = "claude-sonnet-4-5-20250929", api_key: str | None = None):
        self._model = model
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def generate(self, *, system: str, prompt: str, max_tokens: int = 4096) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text

    def generate_json(self, *, system: str, prompt: str, max_tokens: int = 4096) -> dict:
        text = self.generate(system=system, prompt=prompt, max_tokens=max_tokens)
        return _parse_json(text)


def _parse_json(text: str) -> dict:
    """Extract JSON from text, handling markdown code fences."""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text.strip())
