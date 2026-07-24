"""Google Gemini (Veo) video generation provider."""

from __future__ import annotations

import os
import time
from pathlib import Path

from showrunner.providers.video.base import VideoProvider

POLL_INTERVAL = 10  # seconds
MAX_POLL_ATTEMPTS = 60  # 10 minutes max

SUPPORTED_ASPECT_RATIOS = {"16:9", "9:16"}

#: Durations the Veo API actually accepts. The API's own error message
#: ("provide a value between 4 and 8, inclusive") describes this as a
#: continuous range, but odd values inside that range (5, 7) are rejected
#: too — confirmed live. Only these three discrete values work.
API_DURATIONS = (4, 6, 8)


def quantize_duration(requested: int) -> int:
    """Smallest API-supported duration that covers `requested` seconds.

    Requests longer than the maximum are capped at it (compose-time
    trimming, same convention as the MiniMax provider's own
    quantize_duration, can only shorten a clip, not extend one).
    """
    for supported in API_DURATIONS:
        if requested <= supported:
            return supported
    return API_DURATIONS[-1]


class GeminiVideoProvider(VideoProvider):
    """Google Gemini (Veo) — AI video generation via google-genai SDK."""

    # Class-level defaults so instances created without __init__ (e.g. via
    # __new__ in tests) still behave correctly.
    _video_seconds: float = 0.0
    _clips: int = 0
    _generate_audio: bool | None = None

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "veo-3.1-generate-preview",
        generate_audio: bool | None = None,
    ):
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Google API key required. Set GOOGLE_API_KEY or GEMINI_API_KEY, or pass api_key="
            )
        self._model = model
        # E5: Veo 3+ can generate native clip audio (ambient/foley) —
        # useful for formats with no TTS narration to layer over it (e.g.
        # ASMR). Left unset (None) by default and OMITTED from the request
        # entirely: the google-genai API rejects `generate_audio` outright
        # ("only supported in Gemini Enterprise Agent Platform mode, not in
        # Gemini Developer API mode") for the plain api_key auth this
        # provider uses — confirmed via a live call, not documented in the
        # SDK reference. Only pass True/False explicitly if you know your
        # account is on Vertex/Enterprise auth.
        self._generate_audio = generate_audio

        from google import genai

        self._client = genai.Client(api_key=self._api_key)

    def generate(self, prompt: str, *, duration: int, aspect_ratio: str, output_path: Path) -> Path:
        """Submit video generation, poll until complete, download result."""
        from google.genai import types

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ar = aspect_ratio if aspect_ratio in SUPPORTED_ASPECT_RATIOS else "16:9"
        api_duration = quantize_duration(duration)

        config_kwargs = {
            "aspect_ratio": ar,
            "number_of_videos": 1,
            "duration_seconds": api_duration,
        }
        if self._generate_audio is not None:
            config_kwargs["generate_audio"] = self._generate_audio

        operation = self._client.models.generate_videos(
            model=self._model,
            prompt=prompt,
            config=types.GenerateVideosConfig(**config_kwargs),
        )
        print(f"    Submitted video generation: {operation.name}")

        # Poll until complete
        for attempt in range(MAX_POLL_ATTEMPTS):
            if operation.done:
                break
            if attempt % 3 == 0:
                print(f"    Waiting for video... (attempt {attempt + 1})")
            time.sleep(POLL_INTERVAL)
            operation = self._client.operations.get(operation)
        else:
            raise RuntimeError(
                f"Video generation timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s"
            )

        if not operation.response or not operation.response.generated_videos:
            raise RuntimeError(f"Video generation returned no results: {operation}")

        # Download and save
        video = operation.response.generated_videos[0]
        self._client.files.download(file=video.video)
        video.video.save(str(output_path))

        self._video_seconds += float(api_duration)
        self._clips += 1
        return output_path

    def get_usage(self) -> dict:
        return {"video_seconds": self._video_seconds, "clips": self._clips}

    def poll(self, generation_id: str) -> tuple[str, str | None]:
        """Check generation status using operation name."""
        from google.genai import types

        operation = types.GenerateVideosOperation(name=generation_id)
        operation = self._client.operations.get(operation)

        if operation.done:
            if operation.response and operation.response.generated_videos:
                return "completed", generation_id
            return "failed", None
        return "processing", None
