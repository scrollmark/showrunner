"""Remotion video render provider."""

from __future__ import annotations

import json
import subprocess
from importlib import resources
from pathlib import Path

from showrunner.providers.render.base import RenderProvider

TEMPLATE_PACKAGE = "showrunner.providers.render.template"


class RemotionRenderProvider(RenderProvider):
    """Render videos using Remotion."""

    def __init__(self, fps: int = 30):
        self.fps = fps

    def setup(self, work_dir: Path) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        template_dir = resources.files(TEMPLATE_PACKAGE)
        _copy_resource_tree(template_dir, work_dir)
        (work_dir / "src" / "scenes").mkdir(parents=True, exist_ok=True)
        (work_dir / "public" / "audio").mkdir(parents=True, exist_ok=True)
        # Install Node deps
        subprocess.run(["npm", "install", "--silent"], cwd=str(work_dir), check=True, capture_output=True)

    def write_preset_tokens(self, work_dir: Path, preset: dict) -> Path:
        """Materialize the active style preset as typed TypeScript for the
        Remotion template to import. Creates `src/tokens/preset.generated.ts`,
        which is gitignored inside the template but must exist before any
        scene code is rendered.
        """
        tokens_dir = work_dir / "src" / "tokens"
        tokens_dir.mkdir(parents=True, exist_ok=True)
        body = json.dumps(preset, indent=2)
        generated = tokens_dir / "preset.generated.ts"
        generated.write_text(
            "// GENERATED at render setup from the active style preset. Do not edit.\n"
            'import type { Preset } from "./schema";\n\n'
            f"export const preset: Preset = {body} as const;\n"
        )
        return generated

    def render(self, *, work_dir: Path, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["npx", "remotion", "render", "src/index.ts", "main", str(output_path)],
            cwd=str(work_dir), capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Remotion render failed:\n{result.stderr}")
        return output_path

    def preview(self, work_dir: Path) -> None:
        subprocess.Popen(["npx", "remotion", "studio"], cwd=str(work_dir))

    def validate_scene(self, work_dir: Path, scene_id: str) -> tuple[bool, str]:
        """Type-check a scene file using tsc."""
        result = subprocess.run(
            ["npx", "tsc", "--noEmit"], cwd=str(work_dir), capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, ""
        scene_errors = [l for l in result.stderr.splitlines() if scene_id in l.lower() or "error TS" in l]
        return False, "\n".join(scene_errors) if scene_errors else result.stderr


def _copy_resource_tree(src, dest: Path) -> None:
    """Recursively copy importlib resource tree to dest, skipping __pycache__ and __init__.py."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in ("__init__.py", "__pycache__"):
            continue
        child_dest = dest / item.name
        if hasattr(item, "is_dir") and callable(item.is_dir) and item.is_dir():
            _copy_resource_tree(item, child_dest)
        else:
            child_dest.parent.mkdir(parents=True, exist_ok=True)
            child_dest.write_bytes(item.read_bytes())
