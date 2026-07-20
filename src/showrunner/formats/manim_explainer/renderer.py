"""Manim CLI invocation — renders one Scene subclass to an MP4 clip."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT = 600  # seconds per scene render

INSTALL_HINT = (
    "manim CLI not found. Install the optional dependency group with "
    "`pip install \"showrunner[manim]\"` and make sure a LaTeX toolchain "
    "(e.g. TinyTeX or TeX Live) is on PATH for MathTex/Tex."
)


def manim_available() -> bool:
    """True if the `manim` CLI is on PATH."""
    return shutil.which("manim") is not None


def render_scene(
    scene_file: Path,
    scene_class: str,
    output_path: Path,
    *,
    media_dir: Path,
    resolution: tuple[int, int] = (1080, 1920),
    quality: str = "m",
    fps: int = 30,
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[bool, str]:
    """Render one Manim Scene subclass to `output_path`.

    Returns (ok, error). On failure `error` carries the manim
    stderr/traceback so the codegen repair loop can feed it back to
    the LLM. Raises RuntimeError only when manim itself is missing —
    that is an environment problem, not a code problem, and must not
    burn repair-loop retries.
    """
    scene_file = Path(scene_file)
    output_path = Path(output_path)
    media_dir = Path(media_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    width, height = resolution
    cmd = [
        "manim", "render",
        f"-q{quality}",
        "--format", "mp4",
        "-r", f"{width},{height}",
        "--fps", str(fps),
        "--media_dir", str(media_dir),
        "-o", output_path.stem,
        str(scene_file),
        scene_class,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise RuntimeError(INSTALL_HINT) from None
    except subprocess.TimeoutExpired:
        return False, f"manim render timed out after {timeout}s for {scene_class}"

    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "manim render failed with no output")

    # Manim nests output under media_dir/videos/<file_stem>/<quality_dir>/;
    # the exact quality dirname depends on resolution/fps, so glob for the
    # produced file instead of reconstructing the path.
    produced = sorted(
        media_dir.rglob(f"{output_path.stem}.mp4"),
        key=lambda p: p.stat().st_mtime,
    )
    if not produced:
        return False, f"manim reported success but produced no {output_path.stem}.mp4 under {media_dir}"

    shutil.move(str(produced[-1]), str(output_path))
    return True, ""
