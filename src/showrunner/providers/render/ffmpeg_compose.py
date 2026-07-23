"""FFmpeg compositing filtergraph builders for the `composite` format (E4).

A scene's `layers` (see `showrunner.plan.Scene.layers`) use one of two
composition modes, verified against a real ffmpeg build (chromakey,
overlay positioning, hstack/vstack, and fontconfig-based drawtext all
require `ffmpeg` built with `--enable-libass`-adjacent flags — in
practice `--enable-libfontconfig --enable-libfreetype`; Homebrew's
default `ffmpeg` formula lacks these, `ffmpeg-full` has them):

- **Overlay mode**: one `role="base"` layer (listed first) with zero or
  more `"pip"` / `"chromakey"` / `"image"` layers drawn on top of it,
  positioned by `rect` (fractions of the canvas, 0.0-1.0).
- **Stack mode**: two or more `"hstack"` / `"vstack"` layers with no
  base, evenly splitting the canvas, each with an optional `label`
  caption burned in via `drawtext`.

A scene must use exactly one mode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_CHROMAKEY_COLOR = "0x00FF00"
DEFAULT_CHROMAKEY_SIMILARITY = 0.1
DEFAULT_CHROMAKEY_BLEND = 0.2

STACK_ROLES = {"hstack", "vstack"}
OVERLAY_ROLES = {"base", "pip", "chromakey", "image"}


def _rect_to_px(rect: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x, y, w, h = rect
    return (round(x * width), round(y * height), round(w * width), round(h * height))


def _escape_drawtext(text: str) -> str:
    """Escape a label for use inside a `drawtext` filter argument.

    The filter parser treats `\\`, `:`, `'`, and `%` specially.
    """
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def build_overlay_filtergraph(layers: list[dict], *, width: int, height: int) -> tuple[str, str]:
    """Build the `-filter_complex` string for overlay mode.

    `layers[0]` must be the base (role="base"); `layers[1:]` are drawn on
    top in order (later layers on top of earlier ones). Assumes each
    layer's file is fed to ffmpeg as `-i` in the same order as `layers`
    (so layer `i` is input stream `i`). Returns (filter_complex, output_label).
    """
    if not layers or layers[0]["role"] != "base":
        raise ValueError("Overlay-mode scenes must list the base layer (role='base') first")

    parts = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1[base0]"
    ]
    current = "base0"
    for i, layer in enumerate(layers[1:], start=1):
        role = layer["role"]
        if role not in OVERLAY_ROLES or role == "base":
            raise ValueError(f"Unexpected overlay-mode role {role!r} for layer {layer.get('id')!r}")
        rect = layer.get("rect", [0.0, 0.0, 1.0, 1.0])
        rx, ry, rw, rh = _rect_to_px(rect, width, height)
        scaled_label = f"ov{i}"
        if role == "chromakey":
            color = layer.get("key_color", DEFAULT_CHROMAKEY_COLOR)
            parts.append(
                f"[{i}:v]chromakey={color}:{DEFAULT_CHROMAKEY_SIMILARITY}:{DEFAULT_CHROMAKEY_BLEND},"
                f"scale={rw}:{rh}[{scaled_label}]"
            )
        else:  # pip, image
            parts.append(f"[{i}:v]scale={rw}:{rh}[{scaled_label}]")
        out_label = f"comp{i}"
        parts.append(f"[{current}][{scaled_label}]overlay=x={rx}:y={ry}[{out_label}]")
        current = out_label
    return ";".join(parts), current


def build_stack_filtergraph(
    layers: list[dict], *, width: int, height: int, direction: str
) -> tuple[str, str]:
    """Build the `-filter_complex` string for hstack/vstack mode.

    Each layer is scaled+cropped to an even share of the canvas and
    optionally labeled via `drawtext`. Assumes layer `i` is input stream
    `i`. Returns (filter_complex, output_label).
    """
    if direction not in STACK_ROLES:
        raise ValueError(f"direction must be 'hstack' or 'vstack', got {direction!r}")
    n = len(layers)
    if n < 2:
        raise ValueError("Stack mode needs at least 2 layers")

    seg_w, seg_h = (width // n, height) if direction == "hstack" else (width, height // n)

    parts = []
    scaled_labels = []
    for i, layer in enumerate(layers):
        scale_label = f"seg{i}"
        chain = f"[{i}:v]scale={seg_w}:{seg_h}:force_original_aspect_ratio=increase,crop={seg_w}:{seg_h}"
        label_text = layer.get("label")
        if label_text:
            escaped = _escape_drawtext(label_text)
            chain += (
                f",drawtext=font=Sans:text='{escaped}':x=(w-text_w)/2:y=h-text_h-20"
                f":fontsize=36:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=10"
            )
        chain += f"[{scale_label}]"
        parts.append(chain)
        scaled_labels.append(scale_label)

    inputs = "".join(f"[{lbl}]" for lbl in scaled_labels)
    out_label = "stacked"
    parts.append(f"{inputs}{direction}=inputs={n}[{out_label}]")
    return ";".join(parts), out_label


def composite_scene(
    layer_paths: list[Path],
    layer_specs: list[dict],
    *,
    output_path: Path,
    width: int,
    height: int,
    duration: float,
) -> Path:
    """Composite one scene's resolved layer files into a single clip.

    `layer_paths` must be in the same order as `layer_specs` (the
    scene's `layers` list) — already-resolved (generated or
    `file://`-ingested) per-layer source files.
    """
    roles = {layer["role"] for layer in layer_specs}
    is_stack = bool(roles & STACK_ROLES)
    if is_stack and (roles - STACK_ROLES):
        raise ValueError("A scene's layers must be either base+overlays or all hstack/vstack, not both")

    if is_stack:
        direction = "hstack" if "hstack" in roles else "vstack"
        filter_complex, out_label = build_stack_filtergraph(
            layer_specs, width=width, height=height, direction=direction
        )
    else:
        filter_complex, out_label = build_overlay_filtergraph(layer_specs, width=width, height=height)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["ffmpeg", "-y"]
    for path, spec in zip(layer_paths, layer_specs):
        if spec["role"] == "image":
            cmd += ["-loop", "1"]
        cmd += ["-i", str(path)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{out_label}]",
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-an",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg composite failed:\n{result.stderr}")
    return output_path
