"""Minimax video generation provider.

Targets the MiniMax Hailuo video API (``MiniMax-Hailuo-02`` by default).
Two API realities shape this provider:

- **Clip length is quantized**: Hailuo generates 6s or 10s clips only. The
  requested ``duration`` is mapped to the smallest quantized length that
  covers it; the ai-video compose step trims clips back to the storyboard's
  scene duration, so scenes stay in sync with narration.
- **Output is landscape-only** (``768P``/``1080P``; no aspect-ratio
  parameter). ``aspect_ratio`` is accepted for interface compatibility but
  vertical output is produced render-side: compose center-crops the
  landscape frame to the target aspect. Prompts for vertical content should
  keep the subject centered.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from showrunner.providers.video.base import VideoProvider

DEFAULT_MODEL = "MiniMax-Hailuo-02"
DEFAULT_RESOLUTION = "1080P"  # or "768P"
DEFAULT_BASE_URL = "https://api.minimax.io/v1"

#: Clip lengths the Hailuo API actually generates.
API_DURATIONS = (6, 10)

POLL_INTERVAL = 10  # seconds
MAX_POLL_ATTEMPTS = 60  # 10 minutes max


def _raise_if_base_resp_error(data: dict) -> None:
    """MiniMax wraps every response (success or application-level error) in
    ``base_resp: {status_code, status_msg}``. ``status_code != 0`` — e.g. a
    plan/quota mismatch like "your current token plan not support model,
    MiniMax-Hailuo-02-6s-1080p" — still comes back HTTP 200 with an empty
    ``task_id``/``file_id``, so callers must check this explicitly or they'll
    silently poll a bogus id until the 10-minute timeout."""
    base_resp = data.get("base_resp") or {}
    status_code = base_resp.get("status_code", 0)
    if status_code:
        raise RuntimeError(
            f"MiniMax API error {status_code}: {base_resp.get('status_msg', 'unknown error')}"
        )


def quantize_duration(requested: int) -> int:
    """Smallest API-supported clip length that covers ``requested`` seconds.

    Requests longer than the maximum are capped at it (the compose step can
    only trim, not extend).
    """
    for supported in API_DURATIONS:
        if requested <= supported:
            return supported
    return API_DURATIONS[-1]


class MinimaxVideoProvider(VideoProvider):
    """Minimax — AI video generation API."""

    # Usage counters — class-level defaults so instances created without
    # __init__ (e.g. via __new__ in tests) still report usage correctly.
    _video_seconds: float = 0.0
    _clips: int = 0

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        resolution: str = DEFAULT_RESOLUTION,
        base_url: str = DEFAULT_BASE_URL,
    ):
        self._api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        if not self._api_key:
            raise ValueError("Minimax API key required. Set MINIMAX_API_KEY or pass api_key=")
        self._model = model
        self._resolution = resolution
        self._base_url = base_url.rstrip("/")

    def generate(self, prompt: str, *, duration: int, aspect_ratio: str, output_path: Path) -> Path:
        """Submit video generation, poll until complete, download result.

        ``aspect_ratio`` is unused by the API (landscape-only output; see the
        module docstring) — vertical framing is a render-side crop.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        api_duration = quantize_duration(duration)
        with httpx.Client(timeout=60) as client:
            # Submit generation
            task_id = self._submit(client, prompt, api_duration)
            print(f"    Submitted video generation: {task_id}")

            # Poll until complete
            file_id = self._wait_for_completion(client, task_id)

            # Download
            self._download(client, file_id, output_path)

        self._video_seconds += float(api_duration)
        self._clips += 1
        return output_path

    def get_usage(self) -> dict:
        return {"video_seconds": self._video_seconds, "clips": self._clips}

    def poll(self, generation_id: str) -> tuple[str, str | None]:
        """Check generation status."""
        with httpx.Client(timeout=30) as client:
            resp = client.get(
                f"{self._base_url}/query/video_generation",
                params={"task_id": generation_id},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
        _raise_if_base_resp_error(data)

        status_map = {
            "Queueing": "pending",
            "Processing": "processing",
            "Success": "completed",
            "Failed": "failed",
        }
        status = status_map.get(data.get("status", ""), "pending")
        file_id = data.get("file_id") if status == "completed" else None
        return status, file_id

    def _submit(self, client: httpx.Client, prompt: str, duration: int) -> str:
        resp = client.post(
            f"{self._base_url}/video_generation",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "prompt": prompt,
                "duration": duration,
                "resolution": self._resolution,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        _raise_if_base_resp_error(data)
        return data["task_id"]

    def _wait_for_completion(self, client: httpx.Client, task_id: str) -> str:
        for attempt in range(MAX_POLL_ATTEMPTS):
            resp = client.get(
                f"{self._base_url}/query/video_generation",
                params={"task_id": task_id},
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
            _raise_if_base_resp_error(data)

            status = data.get("status", "")
            if status == "Success":
                return data["file_id"]
            elif status == "Failed":
                raise RuntimeError(f"Video generation failed: {data}")

            if attempt % 3 == 0:
                print(f"    Waiting for video... ({status})")
            time.sleep(POLL_INTERVAL)

        raise RuntimeError(f"Video generation timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")

    def _download(self, client: httpx.Client, file_id: str, output_path: Path) -> None:
        resp = client.get(
            f"{self._base_url}/files/retrieve",
            params={"file_id": file_id},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        _raise_if_base_resp_error(data)
        download_url = data["file"]["download_url"]

        with client.stream("GET", download_url) as stream:
            with open(output_path, "wb") as f:
                for chunk in stream.iter_bytes():
                    f.write(chunk)
