from pathlib import Path
import yaml
from showrunner.config import Config, load_config


def test_default_config():
    cfg = Config()
    assert cfg.default_format == "faceless-explainer"
    assert cfg.default_style == "3b1b-dark"
    assert cfg.providers["llm"] == "anthropic"
    assert cfg.providers["tts"] == "kokoro"


def test_config_from_dict():
    cfg = Config.from_dict({"default_format": "ugc", "providers": {"llm": "openai"}})
    assert cfg.default_format == "ugc"
    assert cfg.providers["llm"] == "openai"
    assert cfg.providers["tts"] == "kokoro"  # default preserved


def test_config_merge():
    base = Config()
    merged = base.merge({"default_style": "bold-neon", "output": {"captions": True}})
    assert merged.default_style == "bold-neon"
    assert merged.output["captions"] is True
    assert merged.default_format == "faceless-explainer"


def test_load_config_from_yaml(tmp_path):
    yaml_file = tmp_path / ".showrunner.yaml"
    yaml_file.write_text(yaml.dump({"default_style": "tech-startup", "providers": {"llm": "openai"}}))
    cfg = load_config(yaml_file)
    assert cfg.default_style == "tech-startup"
    assert cfg.providers["llm"] == "openai"


def test_load_config_missing_file():
    cfg = load_config(Path("/nonexistent/.showrunner.yaml"))
    assert cfg.default_format == "faceless-explainer"
