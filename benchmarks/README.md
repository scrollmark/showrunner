# Benchmarks

Compare video quality across agents and toolchain conditions on identical
briefs. Every condition gets the same brief verbatim; only the toolchain
preamble differs (showrunner staged in the workspace + CLI on PATH, or a
bare workspace). Quality differences are therefore attributable to the
toolchain, not the prompt.

## Run

```bash
showrunner bench run \
  --brief benchmarks/briefs/compound-interest.md \
  --conditions benchmarks/conditions.yaml \
  --out runs/my-run
showrunner bench report runs/my-run   # rebuild report.html any time
```

Each condition runs its agent headless in an isolated workspace with a
deadline; the deliverable contract is `out/final.mp4`. The harness records
wall time, agent-reported cost and turns, and the agent's final summary.

## Judge

Open `runs/<run>/report.html`: side-by-side players, frame strips, media
metadata, and a fillable 1–5 scorecard per video using the seven craft
dimensions from `docs/quality-rubric.md`. `results.json` carries the
machine-readable record.

## Notes

- The bare condition means "the agent as installed on this machine, minus
  showrunner" — other globally-installed tooling remains available to it.
  Record the host setup alongside published numbers.
- Costs are real: each condition is a full autonomous agent run.
- Keep briefs neutral (no toolchain hints) so conditions stay comparable.
