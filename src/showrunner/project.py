"""Project manifests — the persistent identity of a video project directory.

A project is created by `showrunner new` and carries everything the CLI
subcommands need to operate on it (workflow, runtime, style, canvas). The
manifest lives at `<project>/showrunner.json`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_FILENAME = "showrunner.json"

# Canvas sizes per aspect ratio. Shared by every workflow.
DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


@dataclass
class ProjectManifest:
    """Everything `showrunner <cmd> PROJECT` needs to know about a project."""

    name: str
    workflow: str
    runtime: str
    style: str
    aspect_ratio: str = "9:16"
    voice: str = "af_heart"
    speed: float = 1.0
    created_at: str = ""
    hyperframes_version: str | None = None

    @property
    def width(self) -> int:
        return DIMENSIONS[self.aspect_ratio][0]

    @property
    def height(self) -> int:
        return DIMENSIONS[self.aspect_ratio][1]

    def save(self, project_dir: Path) -> Path:
        path = Path(project_dir) / MANIFEST_FILENAME
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, project_dir: Path) -> ProjectManifest:
        path = Path(project_dir) / MANIFEST_FILENAME
        if not path.exists():
            raise FileNotFoundError(
                f"No {MANIFEST_FILENAME} in {project_dir} — is this a showrunner project? "
                "Create one with `showrunner new`."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)
