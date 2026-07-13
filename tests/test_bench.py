"""Tests for the benchmark harness (same brief, matrixed agent conditions)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from showrunner.bench import BenchCondition, build_prompt, load_conditions
from showrunner.bench.report import build_report
from showrunner.bench.runner import run_condition

CONDITIONS_YAML = """
conditions:
  - id: claude-showrunner
    agent: claude
    command: ["claude", "-p", "{prompt}", "--dangerously-skip-permissions",
              "--output-format", "json"]
    toolchain: showrunner
  - id: claude-baseline
    agent: claude
    command: ["claude", "-p", "{prompt}", "--dangerously-skip-permissions",
              "--output-format", "json"]
    toolchain: bare
"""


def test_load_conditions(tmp_path):
    path = tmp_path / "conditions.yaml"
    path.write_text(CONDITIONS_YAML)
    conditions = load_conditions(path)
    assert [c.id for c in conditions] == ["claude-showrunner", "claude-baseline"]
    assert conditions[0].toolchain == "showrunner"
    assert "{prompt}" in conditions[0].command


def test_build_prompt_differs_only_by_toolchain_preamble():
    brief = "Make a 30 second explainer about compound interest."
    with_sr = build_prompt(brief, toolchain="showrunner")
    bare = build_prompt(brief, toolchain="bare")
    assert brief in with_sr and brief in bare
    assert "showrunner" in with_sr.lower()
    assert "showrunner" not in bare.lower()
    assert "out/final.mp4" in with_sr and "out/final.mp4" in bare


def _fake_agent_run(cmd, **kwargs):
    """Simulate the agent producing out/final.mp4 and a JSON result envelope."""
    workspace = Path(kwargs["cwd"])
    (workspace / "out").mkdir(exist_ok=True)
    (workspace / "out" / "final.mp4").write_bytes(b"\x00" * 2048)
    payload = json.dumps({"result": "done", "total_cost_usd": 1.23, "num_turns": 42})
    return MagicMock(returncode=0, stdout=payload, stderr="")


def test_run_condition_collects_artifacts(tmp_path):
    condition = BenchCondition(
        id="claude-showrunner", agent="claude",
        command=["fake-agent", "{prompt}"], toolchain="showrunner",
    )
    repo_root = tmp_path / "repo"
    (repo_root / "skills").mkdir(parents=True)
    (repo_root / "skills" / "INDEX.md").write_text("# index")
    (repo_root / "AGENTS.md").write_text("# agents")

    with patch("showrunner.bench.runner.subprocess.run", side_effect=_fake_agent_run):
        result = run_condition(
            condition, brief="Make a video.", run_dir=tmp_path / "run",
            repo_root=repo_root, timeout_s=60,
        )

    workspace = tmp_path / "run" / "claude-showrunner" / "workspace"
    assert (workspace / "AGENTS.md").exists()  # toolchain files staged
    assert (workspace / "skills" / "INDEX.md").exists()
    assert result["output"] and Path(result["output"]).exists()
    assert result["cost_usd"] == 1.23
    assert result["num_turns"] == 42
    assert result["status"] == "ok"


def test_run_condition_bare_stages_no_toolchain(tmp_path):
    condition = BenchCondition(
        id="claude-baseline", agent="claude",
        command=["fake-agent", "{prompt}"], toolchain="bare",
    )
    with patch("showrunner.bench.runner.subprocess.run", side_effect=_fake_agent_run):
        result = run_condition(
            condition, brief="Make a video.", run_dir=tmp_path / "run",
            repo_root=tmp_path, timeout_s=60,
        )
    workspace = tmp_path / "run" / "claude-baseline" / "workspace"
    assert not (workspace / "AGENTS.md").exists()
    assert result["status"] == "ok"


def test_run_condition_strips_api_billing_env(tmp_path, monkeypatch):
    """Child agents must NOT inherit API-key auth — an inherited
    ANTHROPIC_API_KEY silently overrides the machine's subscription login
    and bills every benchmark run at per-token API prices."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "should-not-leak-either")
    condition = BenchCondition(
        id="claude-baseline", agent="claude",
        command=["fake-agent", "{prompt}"], toolchain="bare",
    )
    captured = {}

    def spy(cmd, **kwargs):
        captured.update(kwargs["env"])
        return _fake_agent_run(cmd, **kwargs)

    with patch("showrunner.bench.runner.subprocess.run", side_effect=spy):
        run_condition(condition, brief="Make a video.", run_dir=tmp_path / "run",
                      repo_root=tmp_path, timeout_s=60)
    assert "ANTHROPIC_API_KEY" not in captured
    assert "ANTHROPIC_AUTH_TOKEN" not in captured


def test_run_condition_can_keep_api_key_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-explicit")
    condition = BenchCondition(
        id="claude-baseline", agent="claude",
        command=["fake-agent", "{prompt}"], toolchain="bare", use_api_key=True,
    )
    captured = {}

    def spy(cmd, **kwargs):
        captured.update(kwargs["env"])
        return _fake_agent_run(cmd, **kwargs)

    with patch("showrunner.bench.runner.subprocess.run", side_effect=spy):
        run_condition(condition, brief="Make a video.", run_dir=tmp_path / "run",
                      repo_root=tmp_path, timeout_s=60)
    assert captured.get("ANTHROPIC_API_KEY") == "sk-ant-explicit"


def test_run_condition_missing_output_is_failure(tmp_path):
    condition = BenchCondition(
        id="claude-baseline", agent="claude",
        command=["fake-agent", "{prompt}"], toolchain="bare",
    )
    with patch("showrunner.bench.runner.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="{}", stderr="")):
        result = run_condition(
            condition, brief="Make a video.", run_dir=tmp_path / "run",
            repo_root=tmp_path, timeout_s=60,
        )
    assert result["status"] == "no-output"
    assert result["output"] is None


def test_build_report_writes_html_and_results(tmp_path):
    run_dir = tmp_path / "run"
    for cid in ("claude-showrunner", "claude-baseline"):
        out = run_dir / cid / "workspace" / "out"
        out.mkdir(parents=True)
        (out / "final.mp4").write_bytes(b"\x00" * 2048)
        (run_dir / cid / "result.json").write_text(json.dumps({
            "condition": cid, "status": "ok", "cost_usd": 1.0, "num_turns": 10,
            "duration_s": 300.0,
            "output": str(out / "final.mp4"),
        }))
    (run_dir / "run.json").write_text(json.dumps({"brief": "Make a video."}))

    with patch("showrunner.bench.report.subprocess.run",
               return_value=MagicMock(returncode=0, stdout="30.0\n1080\n1920", stderr="")):
        report_path = build_report(run_dir, frames=0)

    assert report_path.exists()
    html = report_path.read_text()
    assert "claude-showrunner" in html and "claude-baseline" in html
    assert "Typographic hierarchy" in html  # rubric dimensions present
    results = json.loads((run_dir / "results.json").read_text())
    assert {r["condition"] for r in results["conditions"]} == {
        "claude-showrunner", "claude-baseline",
    }
