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

    # ── Optional cost/usage hooks (see showrunner.costs) ──────────────
    # Non-abstract with null defaults so existing providers keep working.

    def estimate_cost(self, *, input_tokens: int, output_tokens: int) -> float | None:
        """Optional pricing hook: USD for the given token counts.

        Default None — the pipeline falls back to its built-in
        pricing table (showrunner.costs.LLM_PRICING_PER_MTOK).
        """
        return None

    def get_usage(self) -> dict:
        """Optional usage-reporting hook: cumulative usage since this
        provider instance was created. Default reports zeros so
        providers that don't track usage keep working."""
        return {"input_tokens": 0, "output_tokens": 0, "calls": 0}
