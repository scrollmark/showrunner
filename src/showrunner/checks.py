"""`showrunner check` — the manifest-driven quality gate.

Each workflow stage may name a check; this module implements them and
aggregates the results into `check.json`. The report carries a content
fingerprint of the gated artifacts so `showrunner render` can refuse to
render when anything changed after the last passing check.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from showrunner.project import ProjectManifest
from showrunner.storyboard import Finding, validate_storyboard
from showrunner.workflows import WorkflowSpec

# Artifacts the fingerprint covers (whichever exist).
_FINGERPRINT_GLOBS = [
    "storyboard.json",
    "narration.json",
    "music.json",
    "src/Root.tsx",
    "src/scenes/*.tsx",
    "index.html",
]


@dataclass
class CheckContext:
    project_dir: Path
    manifest: ProjectManifest
    spec: WorkflowSpec
    storyboard: dict | None


def _load_storyboard(project_dir: Path) -> dict | None:
    path = project_dir / "storyboard.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _scene_component(scene_id: str) -> str:
    return "".join(w.capitalize() for w in scene_id.split("_"))


def _check_storyboard(ctx: CheckContext) -> list[Finding]:
    if ctx.storyboard is None:
        return [Finding("error", "missing-storyboard", "no parseable storyboard.json")]
    return validate_storyboard(ctx.storyboard, ctx.spec)


def _check_narration(ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    path = ctx.project_dir / "narration.json"
    if not path.exists():
        return [Finding("error", "missing-narration", "no narration.json — run `showrunner tts`")]
    try:
        narration = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [Finding("error", "bad-narration-json", "narration.json is not valid JSON")]

    for scene in (ctx.storyboard or {}).get("scenes", []):
        sid = scene.get("id", "")
        if not (scene.get("narration") or "").strip():
            continue  # silent scene — no audio expected
        entry = narration.get(sid)
        if not entry:
            findings.append(Finding("error", "unnarrated-scene",
                                    f"scene '{sid}' has narration text but no entry "
                                    "in narration.json — rerun `showrunner tts`", sid))
            continue
        if not (entry.get("duration") or 0) > 0:
            findings.append(Finding("error", "bad-duration",
                                    f"scene '{sid}' narration duration must be > 0", sid))
        wav = ctx.project_dir / entry.get("path", "")
        if not wav.exists():
            findings.append(Finding("error", "missing-audio",
                                    f"scene '{sid}' audio file {entry.get('path')} missing", sid))
    return findings


def _check_scenes(ctx: CheckContext) -> list[Finding]:
    from showrunner.formats.faceless_explainer.lint import lint_scene

    findings: list[Finding] = []
    scenes = (ctx.storyboard or {}).get("scenes", [])
    for scene in scenes:
        sid = scene.get("id", "")
        path = ctx.project_dir / "src" / "scenes" / f"{_scene_component(sid)}.tsx"
        if not path.exists():
            findings.append(Finding("error", "missing-scene",
                                    f"expected {path.relative_to(ctx.project_dir)}", sid))
            continue
        for v in lint_scene(path.read_text(encoding="utf-8")):
            findings.append(Finding("error", v.rule,
                                    f"line {v.line_number}: {v.explanation}", sid))

    # One whole-project type pass — cheaper than per-scene tsc runs.
    if not findings or all(f.code != "missing-scene" for f in findings):
        result = subprocess.run(
            ["npx", "tsc", "--noEmit"],
            cwd=str(ctx.project_dir), capture_output=True, text=True,
        )
        if result.returncode != 0:
            combined = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
            findings.append(Finding("error", "type-error", combined or "tsc failed"))
    return findings


def _check_compose(ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    root_path = ctx.project_dir / "src" / "Root.tsx"
    if not root_path.exists():
        return [Finding("error", "missing-root", "no src/Root.tsx — run `showrunner compose`")]
    root = root_path.read_text(encoding="utf-8")
    for scene in (ctx.storyboard or {}).get("scenes", []):
        name = _scene_component(scene.get("id", ""))
        if f'from "./scenes/{name}"' not in root:
            findings.append(Finding("error", "stale-compose",
                                    f"Root.tsx does not import scene '{name}' — "
                                    "rerun `showrunner compose`", scene.get("id")))
    return findings


# Clip starts may drift this far (seconds) from the nearest beat: one frame
# at 30fps.
BEAT_TOLERANCE_S = 1.0 / 30.0

_CLIP_START = re.compile(
    r'class="[^"]*\bclip\b[^"]*"[^>]*\bdata-start="([\d.]+)"', re.DOTALL
)


def _check_music(ctx: CheckContext) -> list[Finding]:
    music_path = ctx.project_dir / "music.json"
    if not music_path.exists():
        return [Finding("error", "missing-music",
                        "no music.json — pick a track (`showrunner music list`), run "
                        "`showrunner music analyze` on it, and record track/bpm/beats")]
    try:
        music = json.loads(music_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [Finding("error", "bad-music-json", "music.json is not valid JSON")]

    findings: list[Finding] = []
    beats = music.get("beats") or []
    if not (music.get("bpm") or 0) > 0 or not beats:
        findings.append(Finding("error", "missing-beats",
                                "music.json needs a positive bpm and a non-empty beats grid"))
    track = music.get("track") or ""
    if not track or not (ctx.project_dir / track).exists():
        findings.append(Finding("error", "missing-track",
                                f"music.json track '{track}' not found in the project"))

    # Beat alignment is checked against the authored composition; before
    # index.html exists there is nothing to align yet.
    index = ctx.project_dir / "index.html"
    if beats and index.exists():
        html = index.read_text(encoding="utf-8")
        for match in _CLIP_START.finditer(html):
            start = float(match.group(1))
            nearest = min(beats, key=lambda b: abs(b - start))
            if abs(nearest - start) > BEAT_TOLERANCE_S:
                findings.append(Finding(
                    "error", "beat-misaligned",
                    f"clip data-start=\"{match.group(1)}\" is {abs(nearest - start):.3f}s "
                    f"off the beat grid (nearest beat {nearest}); snap clip starts to beats",
                ))
    return findings


def _check_hyperframes(ctx: CheckContext) -> list[Finding]:
    from showrunner.providers.render.hyperframes import HyperframesRenderProvider

    if not (ctx.project_dir / "index.html").exists():
        return [Finding("error", "missing-composition",
                        "no index.html — author the composition first")]
    ok, messages = HyperframesRenderProvider().check(ctx.project_dir)
    if ok:
        return []
    return [Finding("error", "runtime-check", m) for m in messages]


CHECKS = {
    "storyboard": _check_storyboard,
    "narration": _check_narration,
    "scenes": _check_scenes,
    "compose": _check_compose,
    "music": _check_music,
    "hyperframes": _check_hyperframes,
}


def fingerprint(project_dir: Path) -> str:
    """Content hash over the gated artifacts. Render compares this against
    the one recorded at check time to detect edits after the last check."""
    h = hashlib.sha256()
    paths: list[Path] = []
    for pattern in _FINGERPRINT_GLOBS:
        if "*" in pattern:
            paths.extend(sorted(project_dir.glob(pattern)))
        elif (project_dir / pattern).exists():
            paths.append(project_dir / pattern)
    for path in paths:
        h.update(str(path.relative_to(project_dir)).encode())
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def run_checks(project_dir: Path) -> dict:
    """Run every check the workflow's stages name; write + return check.json."""
    project_dir = Path(project_dir)
    manifest = ProjectManifest.load(project_dir)
    spec = WorkflowSpec.load(manifest.workflow)
    ctx = CheckContext(
        project_dir=project_dir,
        manifest=manifest,
        spec=spec,
        storyboard=_load_storyboard(project_dir),
    )

    results = []
    for stage in spec.stages:
        if not stage.check:
            continue
        check_fn = CHECKS.get(stage.check)
        if check_fn is None:
            results.append({
                "name": stage.check, "passed": False,
                "findings": [{"level": "error", "code": "unknown-check",
                              "message": f"no check named '{stage.check}'"}],
            })
            continue
        findings = check_fn(ctx)
        errors = [f for f in findings if f.level == "error"]
        results.append({
            "name": stage.check,
            "passed": not errors,
            "findings": [f.to_dict() for f in findings],
        })

    report = {
        "passed": all(r["passed"] for r in results),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint(project_dir),
        "checks": results,
    }
    (project_dir / "check.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report
