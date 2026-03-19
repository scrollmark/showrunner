"""Format discovery and registration via entry points."""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Type

from showrunner.formats.base import Format


class FormatRegistry:
    def __init__(self):
        self._formats: dict[str, Type[Format]] = {}

    def register(self, format_cls: Type[Format]) -> None:
        self._formats[format_cls.name] = format_cls

    def get(self, name: str) -> Format:
        if name not in self._formats:
            raise KeyError(f"Format '{name}' not found. Available: {list(self._formats.keys())}")
        return self._formats[name]()

    def list(self) -> list[str]:
        return sorted(self._formats.keys())

    def load_entry_points(self) -> None:
        eps = entry_points()
        group = eps.select(group="showrunner.formats") if hasattr(eps, "select") else eps.get("showrunner.formats", [])
        for ep in group:
            format_cls = ep.load()
            if isinstance(format_cls, type) and issubclass(format_cls, Format):
                self.register(format_cls)


def get_registry() -> FormatRegistry:
    registry = FormatRegistry()
    registry.load_entry_points()
    return registry
