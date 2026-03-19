# AI Video Format — Design

## Overview

A new built-in showrunner format that generates videos using AI video generation APIs (Minimax, Runway, Kling, etc.) for each scene, then stitches clips together with TTS narration using FFmpeg. No Remotion, no React code.

**Goal:** Prove the showrunner abstraction layers work for fundamentally different video types — new provider category (VideoProvider), new render provider (FFmpeg), same Plan model, same pipeline flow.

## New Provider: VideoProvider

```python
class VideoProvider(ABC):
    """Generate video clips from text prompts."""

    @abstractmethod
    def generate(self, prompt: str, *, duration: int, aspect_ratio: str) -> Path:
        """Generate a video clip. Returns path to downloaded MP4."""

    @abstractmethod
    def poll(self, generation_id: str) -> tuple[str, Path | None]:
        """Check status of async generation. Returns (status, path_or_none)."""
```

Most video APIs are async (submit → poll → download). `generate()` handles the full lifecycle internally. `poll()` is exposed for formats that want parallel generation.

**First implementation:** Minimax (good docs, reasonable pricing, 5s clips). Interface is generic enough for Runway/Kling.

## New Render Provider: FFmpegRenderProvider

```python
class FFmpegRenderProvider(RenderProvider):
    def setup(self, work_dir: Path) -> None:
        # Create clips/ and audio/ directories — no heavy install

    def render(self, *, work_dir: Path, output_path: Path) -> Path:
        # 1. Concatenate scene clips from work_dir/clips/
        # 2. Mix audio from work_dir/audio/
        # 3. Apply crossfade transitions between clips
        # 4. Output final MP4

    def preview(self, work_dir: Path) -> None:
        # Open concatenated video in default player
```

Assumes `ffmpeg` is installed (same assumption level as Remotion assuming Node.js).

## AI Video Format

```python
class AIVideoFormat(Format):
    name = "ai-video"
    description = "AI-generated video clips with narration"
    required_providers = ["llm", "tts", "video", "render"]
```

### Pipeline Flow

```
plan()            → LLM generates storyboard
                    (same Plan model — visual field = video generation prompt)
generate_assets() → For each scene:
                      VideoProvider.generate(scene.visual) → clip MP4
                      TTSProvider.synthesize(scene.narration) → WAV
compose()         → Write FFmpeg concat manifest + audio mix instructions
render()          → FFmpegRenderProvider stitches clips + audio → final MP4
```

### Planner Differences

Same storyboard structure, different system prompt. The LLM writes `visual` fields as video generation prompts rather than animation descriptions:

- Faceless: "Bar chart growing from left to right, showing 5 data points with labels"
- AI Video: "Cinematic aerial shot of ocean waves crashing on rocky coastline, golden hour lighting, slow camera pan right"

### Asset Generation

- Video clips saved to `work_dir/clips/{scene_id}.mp4`
- Audio files saved to `work_dir/audio/{scene_id}.wav`
- Scene duration adjusted to match actual clip length (video APIs may return slightly different durations)
- Parallel generation supported (video APIs are I/O bound)

## Pipeline Changes

`Pipeline._create_providers()` gains:
- `video` provider type: `minimax` (first), later `runway`, `kling`
- `render: ffmpeg` option

Config example:
```yaml
providers:
  llm: anthropic
  tts: kokoro
  video: minimax
  render: ffmpeg

minimax:
  api_key: ...
  model: video-01
```

## What This Tests

1. **New provider category** — VideoProvider proves the provider system isn't limited to LLM/TTS/Render
2. **Non-Remotion render** — FFmpeg proves the render abstraction works for non-React pipelines
3. **Same Plan model** — Scene.visual works as a video gen prompt with zero data model changes
4. **Same pipeline flow** — plan → assets → compose → render works for fundamentally different content
