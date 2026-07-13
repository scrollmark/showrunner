"""The agent surface stays coherent: skills exist, are indexed, and only
reference CLI commands that actually exist."""

import re
from pathlib import Path

from click.testing import CliRunner

from showrunner.cli.main import cli
from showrunner.workflows import WorkflowSpec

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / "skills"


def test_agents_md_routes_to_skills_index():
    text = (REPO / "AGENTS.md").read_text()
    assert "skills/INDEX.md" in text
    assert "showrunner check" in text


def test_skills_index_lists_every_skill_file():
    index = (SKILLS / "INDEX.md").read_text()
    for skill in SKILLS.rglob("*.md"):
        if skill.name == "INDEX.md":
            continue
        rel = skill.relative_to(SKILLS)
        assert str(rel) in index, f"{rel} missing from skills/INDEX.md"


def test_every_workflow_skill_has_a_loadable_spec():
    workflow_dirs = [d for d in (SKILLS / "workflows").iterdir() if d.is_dir()]
    assert workflow_dirs, "no workflow skills found"
    for d in workflow_dirs:
        assert (d / "SKILL.md").exists(), f"{d.name} has no SKILL.md"
        spec = WorkflowSpec.load(d.name)  # raises if manifest missing
        assert spec.stages


def test_skills_reference_only_real_cli_commands():
    commands = set(cli.commands)
    for skill in SKILLS.rglob("*.md"):
        text = skill.read_text()
        for match in re.finditer(r"`showrunner ([a-z][a-z-]*)", text):
            cmd = match.group(1)
            assert cmd in commands, (
                f"{skill.relative_to(REPO)} references `showrunner {cmd}` "
                "which is not a CLI command"
            )


def test_workflows_command_lists_specs():
    result = CliRunner().invoke(cli, ["workflows"])
    assert result.exit_code == 0
    assert "explainer" in result.output
    assert "remotion" in result.output


def test_kinetic_typography_workflow_spec():
    spec = WorkflowSpec.load("kinetic-typography")
    assert spec.runtime == "hyperframes"
    assert [s.name for s in spec.stages] == [
        "storyboard", "narration", "composition", "render",
    ]
    assert spec.stages[2].check == "hyperframes"
    assert spec.constraints["scene_count"][0] == 1  # single-scene pieces allowed
