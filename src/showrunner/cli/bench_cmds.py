"""`showrunner bench ...` — same-brief agent comparison runs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import click


def _default_repo_root() -> Path:
    # Editable installs: src/showrunner/cli/ -> repo root.
    return Path(__file__).resolve().parents[3]


@click.group("bench")
def bench_cli():
    """Benchmark video quality across agents / toolchain conditions."""


@bench_cli.command("run")
@click.option("--brief", "brief_path", type=click.Path(exists=True, dir_okay=False),
              required=True, help="Markdown brief given verbatim to every condition")
@click.option("--conditions", "conditions_path", type=click.Path(exists=True, dir_okay=False),
              required=True, help="conditions.yaml (agent commands × toolchain access)")
@click.option("--out", "out_dir", type=click.Path(), default=None,
              help="Run directory (default: runs/<timestamp>)")
@click.option("--repo-root", type=click.Path(exists=True, file_okay=False), default=None,
              help="Repo root providing AGENTS.md + skills/ for showrunner conditions")
@click.option("--only", default=None, help="Run a single condition id")
@click.option("--timeout", "timeout_s", type=int, default=2400,
              help="Per-condition wall clock limit (seconds)")
def run(brief_path, conditions_path, out_dir, repo_root, only, timeout_s):
    """Run every condition on the same brief; collect outputs + costs."""
    from showrunner.bench import load_conditions
    from showrunner.bench.report import build_report
    from showrunner.bench.runner import run_bench

    try:
        conditions = load_conditions(Path(conditions_path))
    except (ValueError, KeyError) as e:
        raise click.ClickException(str(e)) from None
    if only:
        conditions = [c for c in conditions if c.id == only]
        if not conditions:
            raise click.ClickException(f"no condition with id '{only}'")

    run_dir = Path(out_dir) if out_dir else (
        Path.cwd() / "runs" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    )
    run_bench(
        brief_path=Path(brief_path), conditions=conditions, run_dir=run_dir,
        repo_root=Path(repo_root) if repo_root else _default_repo_root(),
        timeout_s=timeout_s, on_progress=click.echo,
    )
    report_path = build_report(run_dir)
    click.echo(f"report: {report_path}")


@bench_cli.command("report")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--frames", type=int, default=5, help="Frames per video in the strip")
def report(run_dir, frames):
    """(Re)build report.html + results.json for an existing run."""
    from showrunner.bench.report import build_report

    path = build_report(Path(run_dir), frames=frames)
    click.echo(f"report: {path}")
