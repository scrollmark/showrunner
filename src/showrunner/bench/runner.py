"""Run benchmark conditions: stage a workspace, invoke the agent, collect."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from showrunner.bench import BenchCondition, build_prompt

OUTPUT_RELPATH = Path("out") / "final.mp4"


def _stage_toolchain(workspace: Path, toolchain: str, repo_root: Path) -> None:
    if toolchain != "showrunner":
        return
    agents_md = repo_root / "AGENTS.md"
    skills = repo_root / "skills"
    if not agents_md.exists() or not skills.is_dir():
        raise FileNotFoundError(
            f"showrunner toolchain files not found under {repo_root} "
            "(need AGENTS.md + skills/) — pass --repo-root"
        )
    shutil.copy2(agents_md, workspace / "AGENTS.md")
    shutil.copytree(skills, workspace / "skills")


def _toolchain_env(toolchain: str) -> dict:
    """Child env: showrunner conditions get this venv's bin dir on PATH;
    bare conditions get it stripped so `showrunner` isn't reachable."""
    import os

    env = dict(os.environ)
    venv_bin = str(Path(sys.executable).parent)
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p != venv_bin]
    if toolchain == "showrunner":
        parts.insert(0, venv_bin)
    env["PATH"] = os.pathsep.join(parts)
    return env


def run_condition(
    condition: BenchCondition,
    *,
    brief: str,
    run_dir: Path,
    repo_root: Path,
    timeout_s: int = 2400,
) -> dict:
    """Execute one condition; write + return its result record."""
    condition_dir = run_dir / condition.id
    workspace = condition_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _stage_toolchain(workspace, condition.toolchain, repo_root)

    prompt = build_prompt(brief, toolchain=condition.toolchain)
    (condition_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    argv = [part.replace("{prompt}", prompt) for part in condition.command]

    started = time.monotonic()
    status, cost, turns, agent_result = "ok", None, None, None
    try:
        proc = subprocess.run(
            argv, cwd=str(workspace), env=_toolchain_env(condition.toolchain),
            capture_output=True, text=True, timeout=timeout_s,
        )
        (condition_dir / "agent-stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
        (condition_dir / "agent-stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
        if proc.returncode != 0:
            status = f"agent-exit-{proc.returncode}"
        try:
            envelope = json.loads(proc.stdout)
            cost = envelope.get("total_cost_usd")
            turns = envelope.get("num_turns")
            agent_result = envelope.get("result")
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
    except subprocess.TimeoutExpired:
        status = "timeout"
    duration = round(time.monotonic() - started, 1)

    output = workspace / OUTPUT_RELPATH
    if status == "ok" and not output.exists():
        status = "no-output"

    result = {
        "condition": condition.id,
        "agent": condition.agent,
        "toolchain": condition.toolchain,
        "status": status,
        "duration_s": duration,
        "cost_usd": cost,
        "num_turns": turns,
        "output": str(output) if output.exists() else None,
        "agent_summary": (agent_result or "")[:2000] or None,
    }
    (condition_dir / "result.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


def run_bench(
    *,
    brief_path: Path,
    conditions: list[BenchCondition],
    run_dir: Path,
    repo_root: Path,
    timeout_s: int = 2400,
    on_progress=print,
) -> list[dict]:
    brief = Path(brief_path).read_text(encoding="utf-8")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "brief": brief, "brief_path": str(brief_path),
        "conditions": [c.id for c in conditions],
    }, indent=2) + "\n", encoding="utf-8")

    results = []
    for condition in conditions:
        on_progress(f"[{condition.id}] running ({condition.toolchain} toolchain)...")
        result = run_condition(
            condition, brief=brief, run_dir=run_dir,
            repo_root=repo_root, timeout_s=timeout_s,
        )
        on_progress(
            f"[{condition.id}] {result['status']} in {result['duration_s']}s"
            + (f", ${result['cost_usd']:.2f}" if result.get("cost_usd") else "")
        )
        results.append(result)
    return results
