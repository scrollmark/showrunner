"""`showrunner check` — run the workflow's quality gate."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.command()
@click.argument("project", type=click.Path(exists=True, file_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output")
def check(project, as_json):
    """Run every gate the workflow declares; write check.json.

    A passing check is required by `showrunner render` — the report
    fingerprints the project so post-check edits invalidate it.
    """
    from showrunner.checks import run_checks

    try:
        report = run_checks(Path(project))
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from None

    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        for result in report["checks"]:
            mark = "ok" if result["passed"] else "FAIL"
            click.echo(f"[{mark}] {result['name']}")
            for f in result["findings"]:
                where = f" [{f['scene_id']}]" if f.get("scene_id") else ""
                click.echo(f"    {f['level']}[{f['code']}]{where}: {f['message']}")
        click.echo("check passed" if report["passed"] else "check FAILED")
    if not report["passed"]:
        raise SystemExit(1)
