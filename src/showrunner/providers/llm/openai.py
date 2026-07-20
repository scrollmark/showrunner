"""OpenAI (GPT) LLM provider."""

from __future__ import annotations

import json
import re
import threading

import openai

from showrunner.providers.llm.base import LLMProvider


class OpenAILLMProvider(LLMProvider):
    """GPT-powered LLM provider."""

    def __init__(self, model: str = "gpt-4o", api_key: str | None = None):
        self._model = model
        self._client = openai.OpenAI(api_key=api_key) if api_key else openai.OpenAI()
        self._usage_lock = threading.Lock()
        self._input_tokens = 0
        self._output_tokens = 0
        self._calls = 0

    def generate(self, *, system: str, prompt: str, max_tokens: int = 4096) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        self._record_usage(getattr(response, "usage", None))
        return response.choices[0].message.content

    def _record_usage(self, usage: object) -> None:
        """Accumulate token counts from an API response (best-effort)."""
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        with self._usage_lock:
            self._calls += 1
            if isinstance(input_tokens, int):
                self._input_tokens += input_tokens
            if isinstance(output_tokens, int):
                self._output_tokens += output_tokens

    def get_usage(self) -> dict:
        with self._usage_lock:
            return {
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
                "calls": self._calls,
            }

    def generate_json(self, *, system: str, prompt: str, max_tokens: int = 4096) -> dict:
        text = self.generate(system=system, prompt=prompt, max_tokens=max_tokens)
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
        return json.loads(text.strip())
