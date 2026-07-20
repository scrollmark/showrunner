"""Guard the first-party agent skill (skills/showrunner/SKILL.md).

The skill is documentation-as-contract: agents rely on the commands and
paths it names. These tests keep it structurally valid (npx-skills layout,
YAML frontmatter) and catch drift against the things it references.
"""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "showrunner" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists():
    assert SKILL_PATH.is_file()


def test_skill_has_valid_frontmatter(skill_text):
    # npx-skills convention: YAML frontmatter delimited by --- lines,
    # with at least `name` and `description`.
    assert skill_text.startswith("---\n")
    end = skill_text.index("\n---\n", 4)
    meta = yaml.safe_load(skill_text[4:end])
    assert meta["name"] == "showrunner"
    assert isinstance(meta["description"], str)
    assert len(meta["description"].strip()) > 40


def test_skill_covers_core_loop(skill_text):
    # create -> inspect -> refine -> export, plus discovery commands.
    for phrase in [
        "showrunner create",
        "showrunner refine",
        "showrunner init",
        "showrunner styles",
        "showrunner formats",
        "WORKDIR:",
        "--instruction",
        "--auto-approve",
        "export",  # NLE handoff differentiator
        "OTIO",
        "FCPXML",
    ]:
        assert phrase in skill_text, f"skill is missing: {phrase}"


def test_skill_references_existing_quality_rubric(skill_text):
    assert "docs/quality-rubric.md" in skill_text
    assert (REPO_ROOT / "docs" / "quality-rubric.md").is_file()


def test_skill_style_presets_exist(skill_text):
    presets_dir = REPO_ROOT / "src" / "showrunner" / "styles" / "presets"
    known = {p.stem for p in presets_dir.glob("*.json")}
    # Every preset the skill recommends must actually ship.
    recommended = [
        "3b1b-dark",
        "bold-neon",
        "clean-corporate",
        "dramatic-story",
        "pastel-gradient",
        "forest-breath",
        "tech-startup",
        "warm-minimal",
        "sunny-editorial",
        "paper-press",
        "minty-fresh",
    ]
    for name in recommended:
        assert name in skill_text, f"skill does not mention preset: {name}"
        assert name in known, f"skill recommends nonexistent preset: {name}"


def test_skill_formats_exist(skill_text):
    assert "faceless-explainer" in skill_text
    assert "ai-video" in skill_text


def test_readme_documents_skill_install():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/showrunner/SKILL.md" in readme
    assert "npx skills add scrollmark/showrunner" in readme
