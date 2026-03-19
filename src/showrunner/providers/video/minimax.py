"""Minimax video generation provider."""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

from showrunner.providers.video.base import VideoProvider

ASPECT_RATIOS = {
    "16:9": "16:9",
    "9:16": "9:16",
    "1:1": "1:1",
    "4:5": "4:5",
}

POLL_INTERVAL = 10  # seconds
MAX_POLL_ATTEMPTS = 60  # 10 minutes max


class MinimaxVideoProvider(VideoProvider):
    """Minimax — AI video generation API."""

    def __init__(self, api_key: str | None = None, model: str = "video-01-live2d"):
        self._api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        if not self._api_key:
            raise ValueError("Minimax API key required. Set MINIMAX_API_KEY or pass api_key=")
        self._model = model
        self._base_url = "https://api.minimaxi.chat/v1"

    def generate(self, prompt: str, *, duration: int, aspect_ratio: str, output_path: Path) -> Path:
        """Submit video generation, poll until complete, download result."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with httpx.Client(timeout=60) as client:
            # Submit generation
            task_id = self._submit(client, prompt, aspect_ratio)
            print(f"    Submitted video generation: {task_id}")

            # Poll until complete
            file_id = self._wait_for_completion(client, task_id)

            # Download
            self._download(client, file_id, output_path)

        return output_path

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

        status_map = {
            "Queueing": "pending",
            "Processing": "processing",
            "Success": "completed",
            "Failed": "failed",
        }
        status = status_map.get(data.get("status", ""), "pending")
        file_id = data.get("file_id") if status == "completed" else None
        return status, file_id

    def _submit(self, client: httpx.Client, prompt: str, aspect_ratio: str) -> str:
        resp = client.post(
            f"{self._base_url}/video_generation",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._model,
                "prompt": prompt,
            },
        )
        resp.raise_for_status()
        data = resp.json()
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
        download_url = resp.json()["file"]["download_url"]

        with client.stream("GET", download_url) as stream:
            with open(output_path, "wb") as f:
                for chunk in stream.iter_bytes():
                    f.write(chunk)
