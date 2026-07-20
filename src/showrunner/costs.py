"""Cost estimation + usage aggregation for embedded hosts.

Follows the estimate -> reserve -> reconcile lifecycle (OpenMontage's
CostTracker model): `Pipeline.estimate()` gives the host a pre-run
figure to reserve against; actual usage is aggregated from provider
`get_usage()` hooks into the work dir's `showrunner.json` manifest and
the `RenderCompleted` ("done") event, so the host can reconcile
actuals against its reservation.

Nothing here instantiates providers or makes API calls — estimation
works from static pricing tables plus per-format heuristics, and each
provider ABC exposes an optional `estimate_cost()` hook (default None)
that overrides the table when a live provider instance is supplied.

Prices are rough public list prices in USD and are deliberately
conservative — treat estimates as an upper-bound budget figure, not an
invoice.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Pricing tables (USD) ─────────────────────────────────────────────────

#: $ per million tokens (input, output), keyed by LLM provider name.
LLM_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "anthropic": (3.00, 15.00),  # claude-sonnet-4-5
    "openai": (2.50, 10.00),  # gpt-4o
}
DEFAULT_LLM_PRICING: tuple[float, float] = (3.00, 15.00)

#: $ per 1000 characters synthesized, keyed by TTS provider name.
TTS_PRICING_PER_1K_CHARS: dict[str, float] = {
    "kokoro": 0.0,  # local model — free
    "elevenlabs": 0.15,
}
DEFAULT_TTS_PRICING_PER_1K_CHARS: float = 0.15

#: $ per second of generated video, keyed by video provider name.
#: This is the dominant cost for the ai-video format.
VIDEO_PRICING_PER_SECOND: dict[str, float] = {
    "gemini": 0.40,  # Veo 3.1
    "minimax": 0.06,
}
DEFAULT_VIDEO_PRICING_PER_SECOND: float = 0.40

# ── Estimation heuristics ────────────────────────────────────────────────

PLAN_INPUT_TOKENS = 1_500
PLAN_OUTPUT_TOKENS = 1_200
#: Per-scene TSX codegen (faceless-explainer), averaged over retries.
SCENE_CODE_INPUT_TOKENS = 5_500
SCENE_CODE_OUTPUT_TOKENS = 2_200
#: ~150 wpm narration ≈ 15 characters of text per spoken second.
NARRATION_CHARS_PER_SECOND = 15
#: Local render compute per second of output video (informational only —
#: render providers are local, so their USD cost is 0).
RENDER_SECONDS_PER_VIDEO_SECOND: dict[str, float] = {
    "remotion": 2.0,
    "ffmpeg": 0.2,
}


# ── Data model ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StageCostEstimate:
    """One stage's contribution to a `CostEstimate`."""

    stage: str  # "plan" | "scene_code" | "narration" | "video_gen" | "render"
    provider: str  # provider name the price came from
    unit: str  # "llm_tokens" | "tts_characters" | "video_seconds" | "render_seconds"
    quantity: float
    usd: float
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "provider": self.provider,
            "unit": self.unit,
            "quantity": self.quantity,
            "usd": self.usd,
            "note": self.note,
        }


@dataclass(frozen=True)
class CostEstimate:
    """Pre-run cost estimate for a pipeline run.

    Returned by `Pipeline.estimate()`. `total_usd` is the figure a
    host should reserve against before starting the run.
    """

    format: str
    num_scenes: int
    estimated_duration_seconds: float
    stages: tuple[StageCostEstimate, ...] = ()

    @property
    def total_usd(self) -> float:
        return round(sum(s.usd for s in self.stages), 4)

    def to_dict(self) -> dict:
        return {
            "format": self.format,
            "num_scenes": self.num_scenes,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "stages": [s.to_dict() for s in self.stages],
            "total_usd": self.total_usd,
        }


# ── Pricing helpers (provider hook first, table fallback) ────────────────


def _hook_cost(provider: object | None, **metrics) -> float | None:
    """Ask a provider instance's optional `estimate_cost()` hook.
    Returns None when there's no instance, no hook, the hook raises,
    or the hook itself returns None (the ABC default)."""
    if provider is None:
        return None
    hook = getattr(provider, "estimate_cost", None)
    if not callable(hook):
        return None
    try:
        value = hook(**metrics)
    except Exception:
        return None
    return float(value) if isinstance(value, (int, float)) else None


def llm_usd(
    name: str, *, input_tokens: float, output_tokens: float, provider: object | None = None
) -> float:
    hooked = _hook_cost(provider, input_tokens=int(input_tokens), output_tokens=int(output_tokens))
    if hooked is not None:
        return hooked
    in_price, out_price = LLM_PRICING_PER_MTOK.get(name, DEFAULT_LLM_PRICING)
    return input_tokens / 1e6 * in_price + output_tokens / 1e6 * out_price


def tts_usd(name: str, *, characters: float, provider: object | None = None) -> float:
    hooked = _hook_cost(provider, characters=int(characters))
    if hooked is not None:
        return hooked
    per_1k = TTS_PRICING_PER_1K_CHARS.get(name, DEFAULT_TTS_PRICING_PER_1K_CHARS)
    return characters / 1000.0 * per_1k


def video_usd(name: str, *, seconds: float, provider: object | None = None) -> float:
    hooked = _hook_cost(provider, seconds=float(seconds))
    if hooked is not None:
        return hooked
    per_second = VIDEO_PRICING_PER_SECOND.get(name, DEFAULT_VIDEO_PRICING_PER_SECOND)
    return seconds * per_second


# ── Pre-run estimation ───────────────────────────────────────────────────


def estimate_pipeline_cost(
    *,
    format_name: str,
    llm_name: str,
    tts_name: str,
    render_name: str,
    video_name: str | None = None,
    scene_codegen: bool = True,
    num_scenes: int = 6,
    avg_scene_seconds: float = 6.0,
    providers: dict | None = None,
) -> CostEstimate:
    """Build a per-stage `CostEstimate` without touching any API.

    `scene_codegen` is True for code-driven formats (faceless-explainer:
    an LLM writes TSX per scene); `video_name` is set for formats that
    generate video clips (ai-video). `providers` may carry live provider
    instances whose `estimate_cost()` hooks override the pricing tables.
    """
    providers = providers or {}
    total_seconds = num_scenes * avg_scene_seconds
    stages: list[StageCostEstimate] = []

    # Plan: one LLM storyboard call.
    plan_tokens = PLAN_INPUT_TOKENS + PLAN_OUTPUT_TOKENS
    stages.append(
        StageCostEstimate(
            stage="plan",
            provider=llm_name,
            unit="llm_tokens",
            quantity=plan_tokens,
            usd=llm_usd(
                llm_name,
                input_tokens=PLAN_INPUT_TOKENS,
                output_tokens=PLAN_OUTPUT_TOKENS,
                provider=providers.get("llm"),
            ),
            note="storyboard generation",
        )
    )

    # Per-scene codegen (code-driven formats only).
    if scene_codegen:
        in_tokens = num_scenes * SCENE_CODE_INPUT_TOKENS
        out_tokens = num_scenes * SCENE_CODE_OUTPUT_TOKENS
        stages.append(
            StageCostEstimate(
                stage="scene_code",
                provider=llm_name,
                unit="llm_tokens",
                quantity=in_tokens + out_tokens,
                usd=llm_usd(
                    llm_name,
                    input_tokens=in_tokens,
                    output_tokens=out_tokens,
                    provider=providers.get("llm"),
                ),
                note=f"{num_scenes} scenes x TSX codegen (incl. retries)",
            )
        )

    # TTS narration.
    characters = total_seconds * NARRATION_CHARS_PER_SECOND
    stages.append(
        StageCostEstimate(
            stage="narration",
            provider=tts_name,
            unit="tts_characters",
            quantity=characters,
            usd=tts_usd(tts_name, characters=characters, provider=providers.get("tts")),
            note="~150 wpm narration",
        )
    )

    # Video generation (the dominant cost for ai-video).
    if video_name:
        stages.append(
            StageCostEstimate(
                stage="video_gen",
                provider=video_name,
                unit="video_seconds",
                quantity=total_seconds,
                usd=video_usd(
                    video_name, seconds=total_seconds, provider=providers.get("video")
                ),
                note=f"{num_scenes} clips x {avg_scene_seconds:g}s",
            )
        )

    # Render: local compute, informational quantity, $0.
    render_factor = RENDER_SECONDS_PER_VIDEO_SECOND.get(render_name, 1.0)
    stages.append(
        StageCostEstimate(
            stage="render",
            provider=render_name,
            unit="render_seconds",
            quantity=total_seconds * render_factor,
            usd=0.0,
            note="local compute (no direct API cost)",
        )
    )

    return CostEstimate(
        format=format_name,
        num_scenes=num_scenes,
        estimated_duration_seconds=total_seconds,
        stages=tuple(stages),
    )


# ── Actual usage aggregation (reconcile) ─────────────────────────────────


def collect_usage(providers: dict | None) -> dict:
    """Gather per-role usage dicts from provider `get_usage()` hooks.

    Best-effort: roles whose provider lacks the hook, raises, or
    returns a non-dict (e.g. a bare mock) are simply skipped.
    Returns e.g. `{"llm": {"input_tokens": ..., ...}, "tts": {...}}`.
    """
    usage: dict = {}
    for role, provider in (providers or {}).items():
        hook = getattr(provider, "get_usage", None)
        if not callable(hook):
            continue
        try:
            reported = hook()
        except Exception:
            continue
        if isinstance(reported, dict):
            usage[role] = reported
    return usage


def _num(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def usage_cost_usd(
    usage: dict,
    *,
    llm_name: str,
    tts_name: str,
    video_name: str | None = None,
    providers: dict | None = None,
) -> float:
    """Price actual usage (from `collect_usage`) in USD.

    Uses provider `estimate_cost()` hooks when instances are supplied,
    otherwise the static pricing tables. Unknown keys are ignored;
    missing keys count as zero.
    """
    providers = providers or {}
    total = 0.0

    llm = usage.get("llm") or {}
    total += llm_usd(
        llm_name,
        input_tokens=_num(llm.get("input_tokens")),
        output_tokens=_num(llm.get("output_tokens")),
        provider=providers.get("llm"),
    )

    tts = usage.get("tts") or {}
    total += tts_usd(
        tts_name, characters=_num(tts.get("characters")), provider=providers.get("tts")
    )

    if video_name:
        video = usage.get("video") or {}
        total += video_usd(
            video_name,
            seconds=_num(video.get("video_seconds")),
            provider=providers.get("video"),
        )

    return round(total, 6)
