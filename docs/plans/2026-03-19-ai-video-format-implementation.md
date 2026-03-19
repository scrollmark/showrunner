# AI Video Format Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a built-in "ai-video" format that generates videos using AI video generation APIs + FFmpeg, proving the showrunner abstraction works for fundamentally different video types.

**Architecture:** New `VideoProvider` abstract base + Minimax implementation for generating video clips per scene. New `FFmpegRenderProvider` for stitching clips + audio. New `AIVideoFormat` that wires planning (LLM), asset generation (VideoProvider + TTS), and composition (FFmpeg concat manifest). Pipeline updated to handle the new provider types.

**Tech Stack:** Python, httpx (Minimax API), FFmpeg (CLI), existing showrunner framework

---

### Task 1: VideoProvider Base Class

**Files:**
- Create: `src/showrunner/providers/video/__init__.py`
- Create: `src/showrunner/providers/video/base.py`
- Create: `tests/test_video_provider_base.py`

**Step 1: Write the failing test**

```python
# tests/test_video_provider_base.py
import pytest
from showrunner.providers.video.base import VideoProvider


def test_video_provider_is_abstract():
    with pytest.raises(TypeError):
        VideoProvider()


def test_video_provider_has_generate_method():
    assert hasattr(VideoProvider, "generate")


def test_video_provider_has_poll_method():
    assert hasattr(VideoProvider, "poll")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_video_provider_base.py -v`
Expected: FAIL (module not found)

**Step 3: Write implementation**

```python
# src/showrunner/providers/video/__init__.py
```

```python
# src/showrunner/providers/video/base.py
"""Abstract video generation provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class VideoProvider(ABC):
    """Generate video clips from text prompts."""

    @abstractmethod
    def generate(self, prompt: str, *, duration: int, aspect_ratio: str, output_path: Path) -> Path:
        """Generate a video clip from a text prompt.

        Handles the full lifecycle: submit → poll → download.
        Returns path to the downloaded MP4 file.
        """

    @abstractmethod
    def poll(self, generation_id: str) -> tuple[str, str | None]:
        """Check status of an async generation.

        Returns (status, download_url_or_none).
        Status is one of: "pending", "processing", "completed", "failed".
        """
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_video_provider_base.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/showrunner/providers/video/ tests/test_video_provider_base.py
git commit -m "feat: add VideoProvider abstract base class"
```

---

### Task 2: Minimax Video Provider

**Files:**
- Create: `src/showrunner/providers/video/minimax.py`
- Create: `tests/test_video_minimax.py`

**Step 1: Write the failing test**

```python
# tests/test_video_minimax.py
import json
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path

from showrunner.providers.video.minimax import MinimaxVideoProvider
from showrunner.providers.video.base import VideoProvider


def test_minimax_is_video_provider():
    assert issubclass(MinimaxVideoProvider, VideoProvider)


@patch("showrunner.providers.video.minimax.httpx")
def test_generate_submits_and_polls(mock_httpx, tmp_path):
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    # Submit response
    submit_resp = MagicMock()
    submit_resp.json.return_value = {"task_id": "task_123"}
    submit_resp.raise_for_status = MagicMock()

    # Poll response — completed
    poll_resp = MagicMock()
    poll_resp.json.return_value = {
        "status": "Success",
        "file_id": "file_456",
    }
    poll_resp.raise_for_status = MagicMock()

    # Download response
    download_resp = MagicMock()
    download_resp.json.return_value = {
        "file": {"download_url": "https://example.com/video.mp4"},
    }
    download_resp.raise_for_status = MagicMock()

    # Stream download
    stream_ctx = MagicMock()
    stream_resp = MagicMock()
    stream_resp.iter_bytes = MagicMock(return_value=[b"fake_video_data"])
    stream_ctx.__enter__ = MagicMock(return_value=stream_resp)
    stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_client.stream.return_value = stream_ctx

    mock_client.post.side_effect = [submit_resp]
    mock_client.get.side_effect = [poll_resp, download_resp]

    provider = MinimaxVideoProvider.__new__(MinimaxVideoProvider)
    provider._api_key = "test_key"
    provider._model = "video-01-live2d"
    provider._base_url = "https://api.minimaxi.chat/v1"

    output = tmp_path / "clip.mp4"
    result = provider.generate("A cat running", duration=5, aspect_ratio="16:9", output_path=output)
    assert result == output


@patch("showrunner.providers.video.minimax.httpx")
def test_poll_returns_status(mock_httpx):
    mock_client = MagicMock()
    mock_httpx.Client.return_value.__enter__ = MagicMock(return_value=mock_client)
    mock_httpx.Client.return_value.__exit__ = MagicMock(return_value=False)

    resp = MagicMock()
    resp.json.return_value = {"status": "Processing"}
    resp.raise_for_status = MagicMock()
    mock_client.get.return_value = resp

    provider = MinimaxVideoProvider.__new__(MinimaxVideoProvider)
    provider._api_key = "test_key"
    provider._base_url = "https://api.minimaxi.chat/v1"

    status, url = provider.poll("task_123")
    assert status == "processing"
    assert url is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_video_minimax.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/showrunner/providers/video/minimax.py
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
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_video_minimax.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/showrunner/providers/video/minimax.py tests/test_video_minimax.py
git commit -m "feat: add Minimax video generation provider"
```

---

### Task 3: FFmpeg Render Provider

**Files:**
- Create: `src/showrunner/providers/render/ffmpeg.py`
- Create: `tests/test_render_ffmpeg.py`

**Step 1: Write the failing test**

```python
# tests/test_render_ffmpeg.py
from unittest.mock import patch, MagicMock
from pathlib import Path

from showrunner.providers.render.ffmpeg import FFmpegRenderProvider
from showrunner.providers.render.base import RenderProvider


def test_ffmpeg_is_render_provider():
    assert issubclass(FFmpegRenderProvider, RenderProvider)


def test_setup_creates_directories(tmp_path):
    provider = FFmpegRenderProvider()
    work_dir = tmp_path / "work"
    provider.setup(work_dir)
    assert (work_dir / "clips").is_dir()
    assert (work_dir / "audio").is_dir()


def test_build_concat_file(tmp_path):
    provider = FFmpegRenderProvider()
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    clips_dir = work_dir / "clips"
    clips_dir.mkdir()

    # Create fake clip files
    (clips_dir / "hook.mp4").write_bytes(b"fake")
    (clips_dir / "main.mp4").write_bytes(b"fake")

    scene_order = ["hook", "main"]
    concat_path = provider._build_concat_file(work_dir, scene_order)
    assert concat_path.exists()
    content = concat_path.read_text()
    assert "hook.mp4" in content
    assert "main.mp4" in content


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_calls_ffmpeg(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=0)
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "clips").mkdir()
    (work_dir / "audio").mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "scene_order.txt").write_text("hook\n")

    output = tmp_path / "out.mp4"
    result = provider.render(work_dir=work_dir, output_path=output)
    assert result == output
    assert mock_subprocess.run.called


@patch("showrunner.providers.render.ffmpeg.subprocess")
def test_render_raises_on_failure(mock_subprocess, tmp_path):
    mock_subprocess.run.return_value = MagicMock(returncode=1, stderr="Error")
    provider = FFmpegRenderProvider()

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    (work_dir / "concat.txt").write_text("file 'clips/hook.mp4'\n")
    (work_dir / "scene_order.txt").write_text("hook\n")

    import pytest
    with pytest.raises(RuntimeError, match="FFmpeg"):
        provider.render(work_dir=work_dir, output_path=tmp_path / "out.mp4")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_render_ffmpeg.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/showrunner/providers/render/ffmpeg.py
"""FFmpeg video render provider — stitches clips + audio into final video."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from showrunner.providers.render.base import RenderProvider


class FFmpegRenderProvider(RenderProvider):
    """Render videos by concatenating clips and mixing audio with FFmpeg."""

    def __init__(self, crossfade: float = 0.5):
        self.crossfade = crossfade

    def setup(self, work_dir: Path) -> None:
        """Create clips/ and audio/ directories."""
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "clips").mkdir(exist_ok=True)
        (work_dir / "audio").mkdir(exist_ok=True)

    def render(self, *, work_dir: Path, output_path: Path) -> Path:
        """Concatenate clips, mix audio, output final MP4."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        concat_file = work_dir / "concat.txt"
        scene_order_file = work_dir / "scene_order.txt"

        if not concat_file.exists():
            raise RuntimeError("No concat.txt found — compose() must run first")

        # Read scene order for audio mixing
        scene_ids = []
        if scene_order_file.exists():
            scene_ids = [s.strip() for s in scene_order_file.read_text().splitlines() if s.strip()]

        # Step 1: Concatenate video clips
        concat_output = work_dir / "_concat.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                str(concat_output),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg concat failed:\n{result.stderr}")

        # Step 2: Mix audio if available
        audio_files = [work_dir / "audio" / f"{sid}.wav" for sid in scene_ids]
        audio_files = [a for a in audio_files if a.exists()]

        if audio_files:
            # Merge all audio into one track
            audio_concat = work_dir / "_audio_concat.txt"
            audio_concat.write_text(
                "\n".join(f"file '{a}'" for a in audio_files)
            )
            merged_audio = work_dir / "_merged_audio.wav"
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(audio_concat),
                    "-c", "copy",
                    str(merged_audio),
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg audio merge failed:\n{result.stderr}")

            # Combine video + audio
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(concat_output),
                    "-i", str(merged_audio),
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    str(output_path),
                ],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg audio mix failed:\n{result.stderr}")
        else:
            # No audio — just copy
            import shutil
            shutil.copy2(concat_output, output_path)

        return output_path

    def preview(self, work_dir: Path) -> None:
        """Open the concatenated video in default player."""
        concat_output = work_dir / "_concat.mp4"
        if concat_output.exists():
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(concat_output)])
            else:
                subprocess.Popen(["xdg-open", str(concat_output)])

    def _build_concat_file(self, work_dir: Path, scene_order: list[str]) -> Path:
        """Build FFmpeg concat demuxer file from ordered scene IDs."""
        clips_dir = work_dir / "clips"
        lines = []
        for scene_id in scene_order:
            clip = clips_dir / f"{scene_id}.mp4"
            if clip.exists():
                lines.append(f"file '{clip}'")
        concat_path = work_dir / "concat.txt"
        concat_path.write_text("\n".join(lines) + "\n")
        return concat_path
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_render_ffmpeg.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/showrunner/providers/render/ffmpeg.py tests/test_render_ffmpeg.py
git commit -m "feat: add FFmpeg render provider"
```

---

### Task 4: AI Video Format — Planner

**Files:**
- Create: `src/showrunner/formats/ai_video/__init__.py` (placeholder)
- Create: `src/showrunner/formats/ai_video/planner.py`
- Create: `tests/test_ai_video_planner.py`

**Step 1: Write the failing test**

```python
# tests/test_ai_video_planner.py
from unittest.mock import MagicMock
from showrunner.formats.ai_video.planner import generate_plan, STORYBOARD_SYSTEM_PROMPT
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style


def test_generate_plan_returns_plan():
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Ocean Wonders",
        "totalDuration": 30,
        "scenes": [
            {"id": "hook", "duration": 5, "narration": "The ocean hides secrets.", "visual": "Cinematic aerial shot of deep blue ocean, golden hour, slow dolly forward", "transition": "fade"},
            {"id": "reveal", "duration": 10, "narration": "Deep below...", "visual": "Underwater shot of coral reef, fish swimming, light rays from surface", "transition": "fade"},
        ],
    }
    style = resolve_style("dramatic-story")
    plan = generate_plan("Ocean mysteries", style=style, llm=mock_llm)
    assert isinstance(plan, Plan)
    assert plan.title == "Ocean Wonders"
    assert len(plan.scenes) == 2


def test_system_prompt_targets_video_generation():
    """Prompt should guide LLM to write video generation prompts, not code descriptions."""
    assert "camera" in STORYBOARD_SYSTEM_PROMPT.lower() or "cinematic" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "shot" in STORYBOARD_SYSTEM_PROMPT.lower()
    assert "code" not in STORYBOARD_SYSTEM_PROMPT.lower()
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_ai_video_planner.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/showrunner/formats/ai_video/__init__.py
"""AI Video format — generates videos using AI video generation APIs."""
```

```python
# src/showrunner/formats/ai_video/planner.py
"""Storyboard generation for AI video format."""

from __future__ import annotations

from showrunner.plan import Plan
from showrunner.styles.resolver import ResolvedStyle


STORYBOARD_SYSTEM_PROMPT = """You are a creative director for short-form AI-generated video content. You produce storyboards where each scene is a single continuous video clip generated by an AI video model.

OUTPUT FORMAT: Return a JSON object:
{
  "title": "Video Title",
  "totalDuration": <total seconds>,
  "scenes": [
    {
      "id": "<snake_case_id>",
      "duration": 5,
      "narration": "<voiceover text — 1-2 sentences>",
      "visual": "<video generation prompt — describe the shot>",
      "transition": "fade"
    }
  ]
}

VISUAL PROMPT RULES (these are prompts for an AI video generation model):
- Describe a single continuous shot per scene
- Include: subject, action, setting, lighting, camera movement
- Camera terms: pan, tilt, dolly, tracking shot, aerial, close-up, wide shot, medium shot
- Lighting: golden hour, dramatic, soft, neon, natural, moody, bright
- Style: cinematic, documentary, timelapse, slow motion, handheld
- Keep each prompt to 1-3 sentences — specific but concise
- Do NOT mention text overlays, UI elements, charts, or diagrams
- Do NOT reference animation code, React, or programming concepts

STORYBOARD RULES:
- Total video: 25-60 seconds
- Each scene: 5 seconds (AI video models generate fixed-length clips)
- 5-8 scenes total
- Hook in first scene — visually striking opening shot
- End with memorable visual
- Each narration must stand alone (no "as we saw")
- Narration should be conversational, use "you", contractions

CONTENT APPROACH:
- Lead with stunning visuals that complement narration
- Each scene's visual should tell its own micro-story
- Vary shot types (wide → close → medium) for visual rhythm
- Consider visual continuity between adjacent scenes"""


STORYBOARD_USER_TEMPLATE = """Create a storyboard for an AI-generated video about:

TOPIC: {topic}

STYLE CONTEXT:
{style_context}

Remember: the "visual" field is a prompt for an AI video generation model. Describe shots, not animations.

Return ONLY the JSON storyboard."""


def generate_plan(
    topic: str,
    *,
    style: ResolvedStyle,
    llm: object,
    config: dict | None = None,
) -> Plan:
    """Generate a video storyboard optimized for AI video generation."""
    style_context = style.to_prompt_context()
    prompt = STORYBOARD_USER_TEMPLATE.format(topic=topic, style_context=style_context)

    storyboard_dict = llm.generate_json(
        system=STORYBOARD_SYSTEM_PROMPT,
        prompt=prompt,
        max_tokens=4096,
    )

    return Plan.from_dict(storyboard_dict)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_ai_video_planner.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/showrunner/formats/ai_video/ tests/test_ai_video_planner.py
git commit -m "feat: add AI video format planner"
```

---

### Task 5: AI Video Format — Assets (Video Generation + TTS)

**Files:**
- Create: `src/showrunner/formats/ai_video/assets.py`
- Create: `tests/test_ai_video_assets.py`

**Step 1: Write the failing test**

```python
# tests/test_ai_video_assets.py
from unittest.mock import MagicMock
from pathlib import Path

from showrunner.formats.ai_video.assets import generate_all_clips, generate_all_narrations
from showrunner.plan import Plan, Scene


def test_generate_all_clips():
    mock_video = MagicMock()
    mock_video.generate.return_value = Path("/tmp/clip.mp4")

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="Aerial ocean shot"),
            Scene(id="main", duration=5, narration="N", visual="Underwater coral"),
        ],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=Path("/tmp/clips"), aspect_ratio="16:9")
    assert len(clips) == 2
    assert mock_video.generate.call_count == 2


def test_generate_all_clips_parallel():
    mock_video = MagicMock()
    mock_video.generate.return_value = Path("/tmp/clip.mp4")

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="Shot A"),
            Scene(id="main", duration=5, narration="N", visual="Shot B"),
        ],
    )
    clips = generate_all_clips(plan, video=mock_video, output_dir=Path("/tmp/clips"), aspect_ratio="16:9", parallel=True)
    assert len(clips) == 2


def test_generate_all_narrations():
    mock_tts = MagicMock()
    mock_tts.synthesize.return_value = MagicMock(duration=3.5, path=Path("/tmp/test.wav"))

    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="Hello", visual="V"),
            Scene(id="main", duration=5, narration="World", visual="V"),
        ],
    )
    durations = generate_all_narrations(plan, tts=mock_tts, output_dir=Path("/tmp/audio"))
    assert len(durations) == 2
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_ai_video_assets.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/showrunner/formats/ai_video/assets.py
"""Asset generation for AI video format: video clips + TTS narration."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from showrunner.plan import Plan, Scene
from showrunner.providers.tts.base import TTSProvider
from showrunner.providers.video.base import VideoProvider


def generate_all_clips(
    plan: Plan,
    *,
    video: VideoProvider,
    output_dir: Path,
    aspect_ratio: str = "16:9",
    parallel: bool = False,
) -> dict[str, Path]:
    """Generate video clips for all scenes. Returns {scene_id: clip_path}."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(plan.scenes)

    if parallel:
        return _generate_clips_parallel(plan, video=video, output_dir=output_dir, aspect_ratio=aspect_ratio, total=total)

    clips = {}
    for i, scene in enumerate(plan.scenes, 1):
        print(f"  [{i}/{total}] Generating clip: {scene.id}...")
        clip_path = output_dir / f"{scene.id}.mp4"
        video.generate(scene.visual, duration=scene.duration, aspect_ratio=aspect_ratio, output_path=clip_path)
        clips[scene.id] = clip_path
    return clips


def _generate_clips_parallel(plan, *, video, output_dir, aspect_ratio, total):
    clips = {}
    errors = []
    with ThreadPoolExecutor(max_workers=min(3, total)) as pool:
        futures = {}
        for i, scene in enumerate(plan.scenes, 1):
            clip_path = output_dir / f"{scene.id}.mp4"
            future = pool.submit(
                video.generate, scene.visual,
                duration=scene.duration, aspect_ratio=aspect_ratio, output_path=clip_path,
            )
            futures[future] = (scene, clip_path, i)

        for future in as_completed(futures):
            scene, clip_path, index = futures[future]
            try:
                future.result()
                clips[scene.id] = clip_path
                print(f"  [{index}/{total}] {scene.id} done")
            except Exception as e:
                errors.append(f"{scene.id}: {e}")

    if errors:
        raise RuntimeError(f"{len(errors)} clip(s) failed:\n" + "\n".join(errors))
    return clips


def generate_all_narrations(
    plan: Plan,
    *,
    tts: TTSProvider,
    output_dir: Path,
    voice: str = "af_heart",
    speed: float = 1.0,
) -> dict[str, float]:
    """Generate TTS narration for all scenes. Returns {scene_id: duration}."""
    durations = {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for scene in plan.scenes:
        output_path = output_dir / f"{scene.id}.wav"
        result = tts.synthesize(scene.narration, output_path=output_path, voice=voice, speed=speed)
        durations[scene.id] = result.duration

    return durations
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_ai_video_assets.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/showrunner/formats/ai_video/assets.py tests/test_ai_video_assets.py
git commit -m "feat: add AI video format asset generation (clips + TTS)"
```

---

### Task 6: AI Video Format — Main Class

**Files:**
- Modify: `src/showrunner/formats/ai_video/__init__.py`
- Create: `tests/test_ai_video_format.py`

**Step 1: Write the failing test**

```python
# tests/test_ai_video_format.py
from unittest.mock import MagicMock
from pathlib import Path

from showrunner.formats.ai_video import AIVideoFormat
from showrunner.formats.base import Format
from showrunner.feedback import Feedback
from showrunner.plan import Plan, Scene
from showrunner.styles.resolver import resolve_style


def test_is_format_subclass():
    assert issubclass(AIVideoFormat, Format)


def test_format_metadata():
    fmt = AIVideoFormat()
    assert fmt.name == "ai-video"
    assert "video" in fmt.required_providers
    assert "llm" in fmt.required_providers
    assert "tts" in fmt.required_providers
    assert "render" in fmt.required_providers


def test_plan_delegates_to_planner():
    fmt = AIVideoFormat()
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Test", "totalDuration": 10,
        "scenes": [{"id": "hook", "duration": 5, "narration": "N", "visual": "Aerial shot"}],
    }
    style = resolve_style("dramatic-story")
    plan = fmt.plan("test", style, None, mock_llm)
    assert isinstance(plan, Plan)


def test_compose_writes_concat_and_scene_order(tmp_path):
    fmt = AIVideoFormat()
    plan = Plan(
        title="Test", total_duration=10,
        scenes=[
            Scene(id="hook", duration=5, narration="N", visual="V"),
            Scene(id="main", duration=5, narration="N", visual="V"),
        ],
    )
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    (clips_dir / "hook.mp4").write_bytes(b"fake")
    (clips_dir / "main.mp4").write_bytes(b"fake")

    assets = {"clips": {"hook": clips_dir / "hook.mp4", "main": clips_dir / "main.mp4"}, "has_audio": True}
    fmt.compose(plan, assets, tmp_path)

    assert (tmp_path / "concat.txt").exists()
    assert (tmp_path / "scene_order.txt").exists()
    content = (tmp_path / "concat.txt").read_text()
    assert "hook.mp4" in content
    assert "main.mp4" in content


def test_revise_with_text():
    fmt = AIVideoFormat()
    plan = Plan(title="Test", total_duration=10, scenes=[Scene(id="hook", duration=5, narration="N", visual="V")])
    mock_llm = MagicMock()
    mock_llm.generate_json.return_value = {
        "title": "Revised", "totalDuration": 15,
        "scenes": [{"id": "hook", "duration": 5, "narration": "Better", "visual": "Better shot"}],
    }
    feedback = Feedback(level="plan", text="Make visuals more dramatic")
    revised = fmt.revise(plan, feedback, mock_llm)
    assert revised.title == "Revised"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_ai_video_format.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/showrunner/formats/ai_video/__init__.py
"""AI Video format — generates videos using AI video generation APIs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from showrunner.feedback import Feedback
from showrunner.formats.base import Format
from showrunner.formats.ai_video.assets import generate_all_clips, generate_all_narrations
from showrunner.formats.ai_video.planner import generate_plan
from showrunner.plan import Plan
from showrunner.styles.resolver import ResolvedStyle


class AIVideoFormat(Format):
    """AI-generated video clips with narration."""

    name = "ai-video"
    description = "AI-generated video clips stitched with narration"
    required_providers = ["llm", "tts", "video", "render"]

    def plan(self, topic: str, style: Any, config: Any, llm: Any) -> Plan:
        return generate_plan(topic, style=style, llm=llm, config=config)

    def generate_assets(self, plan: Plan, providers: dict, work_dir: Path) -> dict:
        video = providers["video"]
        tts = providers["tts"]

        aspect_ratio = getattr(self, "_aspect_ratio", "16:9")
        voice = getattr(self, "_voice", "af_heart")
        speed = getattr(self, "_speed", 1.0)
        parallel = getattr(self, "_parallel", False)

        # Generate video clips
        clips_dir = work_dir / "clips"
        clips = generate_all_clips(
            plan, video=video, output_dir=clips_dir,
            aspect_ratio=aspect_ratio, parallel=parallel,
        )

        # Generate narrations
        audio_dir = work_dir / "audio"
        durations = generate_all_narrations(
            plan, tts=tts, output_dir=audio_dir, voice=voice, speed=speed,
        )

        return {"clips": clips, "durations": durations, "has_audio": True}

    def compose(self, plan: Plan, assets: dict, work_dir: Path, **kwargs) -> None:
        """Write FFmpeg concat file and scene order for the render provider."""
        clips = assets.get("clips", {})
        scene_order = [scene.id for scene in plan.scenes]

        # Write concat file
        lines = []
        for scene_id in scene_order:
            clip_path = clips.get(scene_id)
            if clip_path and Path(clip_path).exists():
                lines.append(f"file '{clip_path}'")
        concat_path = work_dir / "concat.txt"
        concat_path.write_text("\n".join(lines) + "\n")

        # Write scene order (for audio mixing)
        scene_order_path = work_dir / "scene_order.txt"
        scene_order_path.write_text("\n".join(scene_order) + "\n")

    def revise(self, plan: Plan, feedback: Feedback, llm: Any) -> Plan:
        if feedback.edits:
            return Plan.from_dict({**plan.to_dict(), **feedback.edits})
        if feedback.text:
            revised = llm.generate_json(
                system="You are a video storyboard editor. Revise the storyboard based on feedback. The visual field should be an AI video generation prompt (describe shots, not code). Return valid JSON.",
                prompt=f"Current storyboard:\n{plan.to_json()}\n\nFeedback: {feedback.text}\n\nReturn revised JSON.",
            )
            return Plan.from_dict(revised)
        return plan
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_ai_video_format.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/showrunner/formats/ai_video/__init__.py tests/test_ai_video_format.py
git commit -m "feat: add AIVideoFormat class"
```

---

### Task 7: Wire into Pipeline and Config

**Files:**
- Modify: `src/showrunner/pipeline.py` (add video provider + ffmpeg render to `_create_providers`)
- Modify: `pyproject.toml` (add entry point + httpx dependency)
- Create: `tests/test_pipeline_ai_video.py`

**Step 1: Write the failing test**

```python
# tests/test_pipeline_ai_video.py
from unittest.mock import patch, MagicMock
from showrunner.pipeline import Pipeline
from showrunner.plan import Plan


def test_create_providers_with_video_and_ffmpeg():
    pipeline = Pipeline()
    providers = pipeline._create_providers(
        llm_name="anthropic",
        tts_name="kokoro",
        render_name="ffmpeg",
        provider_config={"minimax": {"api_key": "test"}},
        video_name="minimax",
    )
    assert "llm" in providers
    assert "tts" in providers
    assert "render" in providers
    assert "video" in providers


def test_pipeline_dry_run_ai_video():
    with patch("showrunner.pipeline.get_registry") as mock_reg_fn:
        mock_fmt = MagicMock()
        mock_fmt.plan.return_value = Plan(title="AI Test", total_duration=10, scenes=[])
        mock_reg = MagicMock()
        mock_reg.get.return_value = mock_fmt
        mock_reg_fn.return_value = mock_reg

        pipeline = Pipeline(format_name="ai-video")
        result = pipeline.run("Ocean mysteries", dry_run=True)
        assert isinstance(result, Plan)
        assert result.title == "AI Test"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/test_pipeline_ai_video.py -v`
Expected: FAIL

**Step 3: Modify pipeline.py**

Add `video_name` parameter to `_create_providers` and handle video + ffmpeg providers. The `run()` method needs to pass the video provider name from config. Key changes:

In `_create_providers`, add a `video_name: str | None = None` parameter:

```python
# After the render block, add:
if video_name:
    if video_name == "minimax":
        from showrunner.providers.video.minimax import MinimaxVideoProvider
        cfg = provider_config.get("minimax", {})
        providers["video"] = MinimaxVideoProvider(api_key=cfg.get("api_key"), model=cfg.get("model", "video-01-live2d"))
    else:
        raise ValueError(f"Unknown video provider: {video_name}")
```

Add `render_name == "ffmpeg"` handling:

```python
elif render_name == "ffmpeg":
    from showrunner.providers.render.ffmpeg import FFmpegRenderProvider
    providers["render"] = FFmpegRenderProvider()
```

In `run()`, pass `video_name` from config:

```python
providers = self._create_providers(
    llm_name=self.config.providers.get("llm", "anthropic"),
    tts_name=self.config.providers.get("tts", "kokoro"),
    render_name=self.config.providers.get("render", "remotion"),
    provider_config=self.config.provider_config,
    video_name=self.config.providers.get("video"),
)
```

**Step 4: Modify pyproject.toml**

Add to `[project.optional-dependencies]`:
```toml
minimax = ["httpx>=0.27"]
```

Update `all` extra:
```toml
all = ["showrunner[openai,kokoro,elevenlabs,minimax]"]
```

Add entry point:
```toml
[project.entry-points."showrunner.formats"]
faceless-explainer = "showrunner.formats.faceless_explainer:FacelessExplainerFormat"
ai-video = "showrunner.formats.ai_video:AIVideoFormat"
```

**Step 5: Run tests**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add src/showrunner/pipeline.py pyproject.toml tests/test_pipeline_ai_video.py
git commit -m "feat: wire AI video format into pipeline and config"
```

---

### Task 8: Integration Test + Verify CLI

**Files:**
- Create: `tests/test_ai_video_integration.py`

**Step 1: Write integration test**

```python
# tests/test_ai_video_integration.py
"""Integration test for AI video format with mocked providers."""

from unittest.mock import MagicMock, patch
from pathlib import Path

from showrunner.formats.ai_video import AIVideoFormat
from showrunner.plan import Plan, Scene
from showrunner.styles.resolver import resolve_style


def test_ai_video_full_flow(tmp_path):
    """Test complete format flow: plan → assets → compose."""
    fmt = AIVideoFormat()
    fmt._style = resolve_style("dramatic-story")
    fmt._aspect_ratio = "16:9"
    fmt._voice = "af_heart"
    fmt._speed = 1.0
    fmt._parallel = False

    # Mock providers
    mock_llm = MagicMock()
    mock_video = MagicMock()
    mock_tts = MagicMock()

    # Plan
    mock_llm.generate_json.return_value = {
        "title": "Ocean Wonders",
        "totalDuration": 15,
        "scenes": [
            {"id": "hook", "duration": 5, "narration": "The ocean hides secrets.", "visual": "Aerial shot of ocean waves, golden hour"},
            {"id": "deep", "duration": 5, "narration": "Miles below the surface...", "visual": "Underwater shot, bioluminescent creatures"},
            {"id": "cta", "duration": 5, "narration": "Follow for more.", "visual": "Sunset over calm ocean, drone shot pulling back"},
        ],
    }
    plan = fmt.plan("Ocean mysteries", fmt._style, None, mock_llm)
    assert len(plan.scenes) == 3

    # Assets
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    for scene in plan.scenes:
        # Create fake clip files so compose can find them
        (clips_dir / f"{scene.id}.mp4").write_bytes(b"fake_video")

    mock_video.generate.side_effect = lambda prompt, *, duration, aspect_ratio, output_path: output_path
    mock_tts.synthesize.return_value = MagicMock(duration=4.0, path=Path("/tmp/audio.wav"))

    providers = {"llm": mock_llm, "video": mock_video, "tts": mock_tts}
    assets = fmt.generate_assets(plan, providers, tmp_path)
    assert "clips" in assets
    assert mock_video.generate.call_count == 3
    assert mock_tts.synthesize.call_count == 3

    # Compose
    fmt.compose(plan, assets, tmp_path)
    assert (tmp_path / "concat.txt").exists()
    assert (tmp_path / "scene_order.txt").exists()

    concat_content = (tmp_path / "concat.txt").read_text()
    assert "hook.mp4" in concat_content
    assert "deep.mp4" in concat_content
    assert "cta.mp4" in concat_content

    scene_order = (tmp_path / "scene_order.txt").read_text().strip().split("\n")
    assert scene_order == ["hook", "deep", "cta"]
```

**Step 2: Run all tests**

Run: `cd /Users/nikhil/dropyacht/showrunner && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Verify CLI shows new format**

```bash
cd /Users/nikhil/dropyacht/showrunner
pip install -e ".[dev]"
showrunner formats
# Expected: should list both faceless-explainer and ai-video
```

**Step 4: Commit**

```bash
git add tests/test_ai_video_integration.py
git commit -m "test: add AI video format integration test"
```

---

## Task Summary

| Task | Description | Key Output |
|------|-------------|------------|
| 1 | VideoProvider base class | New provider category |
| 2 | Minimax video provider | First video gen implementation |
| 3 | FFmpeg render provider | Non-Remotion renderer |
| 4 | AI video planner | Storyboard with video gen prompts |
| 5 | AI video assets | Clip generation + TTS |
| 6 | AIVideoFormat class | Format wiring |
| 7 | Pipeline + config wiring | End-to-end integration |
| 8 | Integration test + CLI verify | Prove it works |
