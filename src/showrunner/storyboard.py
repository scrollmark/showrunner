"""Storyboard validation against a workflow spec's constraints.

The storyboard is agent-authored JSON (same shape `Plan` serializes:
camelCase, but snake_case is accepted too). Validation is pure — it
returns findings instead of raising, so callers can render them for
humans or machines alike.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from showrunner.workflows import WorkflowSpec

SCENE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

ALLOWED_TRANSITIONS = {
    "fade", "slide-left", "slide-right", "slide-up", "slide-down",
    "wipe", "flip", "zoom-in", "cut",
}

# A hook that dwells longer than this reads slow on short-form platforms.
MAX_HOOK_SECONDS = 5


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warning"
    code: str
    message: str
    scene_id: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


def validate_storyboard(data: dict, spec: WorkflowSpec) -> list[Finding]:
    findings: list[Finding] = []
    err = lambda code, msg, sid=None: findings.append(Finding("error", code, msg, sid))  # noqa: E731
    warn = lambda code, msg, sid=None: findings.append(Finding("warning", code, msg, sid))  # noqa: E731

    if not data.get("title"):
        err("missing-title", "storyboard needs a non-empty 'title'")

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        err("missing-scenes", "storyboard needs a non-empty 'scenes' list")
        return findings

    lo, hi = spec.constraints.get("scene_count", [1, 999])
    if not (lo <= len(scenes) <= hi):
        err("scene-count", f"{len(scenes)} scenes; this workflow wants {lo}-{hi}")

    dur_lo, dur_hi = spec.constraints.get("scene_duration", [1, 999])
    seen_ids: set[str] = set()
    total = 0
    for i, scene in enumerate(scenes):
        sid = scene.get("id") or f"<scene {i}>"
        if not scene.get("id") or not SCENE_ID_PATTERN.match(scene.get("id", "")):
            err("bad-scene-id", f"scene id '{sid}' must be snake_case", sid)
        if sid in seen_ids:
            err("duplicate-scene-id", f"scene id '{sid}' appears more than once", sid)
        seen_ids.add(sid)

        duration = scene.get("duration")
        if not isinstance(duration, (int, float)) or duration <= 0:
            err("scene-duration", f"scene '{sid}' needs a positive numeric duration", sid)
        else:
            total += duration
            if not (dur_lo <= duration <= dur_hi):
                err(
                    "scene-duration",
                    f"scene '{sid}' is {duration}s; this workflow wants {dur_lo}-{dur_hi}s",
                    sid,
                )

        narration = scene.get("narration", "")
        if not isinstance(narration, str):
            err("bad-narration", f"scene '{sid}' narration must be a string", sid)
        elif not narration.strip():
            warn("empty-narration", f"scene '{sid}' has no narration; tts will skip it", sid)

        if not (scene.get("visual") or "").strip():
            err("empty-visual", f"scene '{sid}' needs a 'visual' description", sid)

        transition = scene.get("transition")
        if transition is not None and transition not in ALLOWED_TRANSITIONS:
            err(
                "bad-transition",
                f"scene '{sid}' transition '{transition}' not in {sorted(ALLOWED_TRANSITIONS)}",
                sid,
            )

    tot_lo, tot_hi = spec.constraints.get("total_duration", [1, 9999])
    if total and not (tot_lo <= total <= tot_hi):
        err("total-duration", f"scenes sum to {total}s; this workflow wants {tot_lo}-{tot_hi}s")

    first = scenes[0]
    if isinstance(first.get("duration"), (int, float)) and first["duration"] > MAX_HOOK_SECONDS:
        warn(
            "slow-hook",
            f"first scene runs {first['duration']}s — open faster (≤{MAX_HOOK_SECONDS}s) "
            "so the hook lands before viewers swipe",
            first.get("id"),
        )

    return findings


def has_errors(findings: list[Finding]) -> bool:
    return any(f.level == "error" for f in findings)
