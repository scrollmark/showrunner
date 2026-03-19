"""OpenAI (GPT) LLM provider."""

from __future__ import annotations

import json
import re

import openai

from showrunner.providers.llm.base import LLMProvider


class OpenAILLMProvider(LLMProvider):
    """GPT-powered LLM provider."""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self._model = model
        self._client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()

    def generate(self, *, system: str, prompt: str, max_tokens: int = 4096) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content

    def generate_json(self, *, system: str, prompt: str, max_tokens: int = 4096) -> dict:
        text = self.generate(system=system, prompt=prompt, max_tokens=max_tokens)
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
        return json.loads(text.strip())
