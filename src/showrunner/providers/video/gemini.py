"""Google Gemini (Veo) video generation provider."""

from __future__ import annotations

import os
import time
from pathlib import Path

from showrunner.providers.video.base import VideoProvider

POLL_INTERVAL = 10  # seconds
MAX_POLL_ATTEMPTS = 60  # 10 minutes max

SUPPORTED_ASPECT_RATIOS = {"16:9", "9:16"}


class GeminiVideoProvider(VideoProvider):
    """Google Gemini (Veo) — AI video generation via google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "veo-3.1-generate-preview",
    ):
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "Google API key required. Set GOOGLE_API_KEY or GEMINI_API_KEY, or pass api_key="
            )
        self._model = model

        from google import genai

        self._client = genai.Client(api_key=self._api_key)

    def generate(self, prompt: str, *, duration: int, aspect_ratio: str, output_path: Path) -> Path:
        """Submit video generation, poll until complete, download result."""
        from google.genai import types

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        ar = aspect_ratio if aspect_ratio in SUPPORTED_ASPECT_RATIOS else "16:9"

        operation = self._client.models.generate_videos(
            model=self._model,
            prompt=prompt,
            config=types.GenerateVideosConfig(
                aspect_ratio=ar,
                number_of_videos=1,
            ),
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

        return output_path

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
