import pytest
from showrunner.formats.base import Format
from showrunner.formats.registry import FormatRegistry


class DummyFormat(Format):
    name = "dummy"
    description = "A test format"
    required_providers = ["llm"]

    def plan(self, topic, style, config, llm):
        pass
    def generate_assets(self, plan, providers, work_dir):
        pass
    def compose(self, plan, assets, work_dir, **kwargs):
        pass
    def revise(self, plan, feedback, llm):
        return plan


def test_format_is_abstract():
    with pytest.raises(TypeError):
        Format()


def test_registry_register_and_get():
    registry = FormatRegistry()
    registry.register(DummyFormat)
    fmt = registry.get("dummy")
    assert isinstance(fmt, DummyFormat)


def test_registry_list():
    registry = FormatRegistry()
    registry.register(DummyFormat)
    assert "dummy" in registry.list()


def test_registry_get_not_found():
    registry = FormatRegistry()
    with pytest.raises(KeyError):
        registry.get("nonexistent")
