"""Workflow specs — the machine-readable contract behind each workflow.

Each workflow ships a `manifest.yaml` as package data. The manifest names
the runtime, the ordered stages with the artifact each produces, and the
named check that gates it (see `showrunner.checks`). Constraints hold the
numeric bounds validators enforce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources

import yaml

WORKFLOWS_PACKAGE = "showrunner.workflows"


@dataclass(frozen=True)
class Stage:
    name: str
    produces: str | None = None
    check: str | None = None


@dataclass
class WorkflowSpec:
    name: str
    description: str
    runtime: str
    stages: list[Stage] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)

    @classmethod
    def load(cls, name: str) -> WorkflowSpec:
        root = resources.files(WORKFLOWS_PACKAGE)
        target = root.joinpath(name).joinpath("manifest.yaml")
        try:
            text = target.read_text(encoding="utf-8")
        except (FileNotFoundError, TypeError, NotADirectoryError):
            raise FileNotFoundError(
                f"Workflow '{name}' not found. Available: {cls.list_all()}"
            ) from None
        data = yaml.safe_load(text)
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            runtime=data["runtime"],
            stages=[
                Stage(
                    name=s["name"],
                    produces=s.get("produces"),
                    check=s.get("check"),
                )
                for s in data.get("stages", [])
            ],
            constraints=data.get("constraints", {}),
        )

    @staticmethod
    def list_all() -> list[str]:
        root = resources.files(WORKFLOWS_PACKAGE)
        names = []
        for entry in root.iterdir():
            if entry.is_dir() and entry.joinpath("manifest.yaml").is_file():
                names.append(entry.name)
        return sorted(names)
