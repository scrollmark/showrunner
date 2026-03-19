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
