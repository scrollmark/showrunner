"""HyperFrames render runtime — single-file HTML compositions via the pinned CLI.

The composition is a plain HTML file with `data-*` timing attributes and one
paused GSAP timeline registered at `window.__timelines["<id>"]`; the CLI
captures it deterministically to video. We pin the npm version so agent-
authored compositions and CI renders don't drift under us.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Pinned CLI version — bump deliberately, alongside skills/craft updates.
HYPERFRAMES_VERSION = "0.7.56"

_SKELETON = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={width}, height={height}" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{
        margin: 0;
        width: {width}px;
        height: {height}px;
        overflow: hidden;
        background: #000;
      }}
    </style>
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{duration}"
      data-width="{width}"
      data-height="{height}"
    >
      <!-- clips go here: <div class="clip" data-start data-duration data-track-index> -->
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""


class HyperframesRenderProvider:
    """Render/check/preview a HyperFrames project directory."""

    def setup(
        self, work_dir: Path, *, width: int = 1080, height: int = 1920,
        duration: int = 30, install: bool = True,
    ) -> None:
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "assets" / "audio").mkdir(parents=True, exist_ok=True)
        (work_dir / "assets" / "images").mkdir(parents=True, exist_ok=True)
        index = work_dir / "index.html"
        if not index.exists():
            index.write_text(
                _SKELETON.format(width=width, height=height, duration=duration),
                encoding="utf-8",
            )

    def _npx(self, *args: str) -> list[str]:
        return ["npx", "-y", f"hyperframes@{HYPERFRAMES_VERSION}", *args]

    def _run(self, argv: list[str], work_dir: Path) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                argv, cwd=str(work_dir), capture_output=True, text=True,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "npx not found — the hyperframes runtime needs Node.js (>= 22) installed."
            ) from None

    def render(self, *, work_dir: Path, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = self._run(
            self._npx("render", "-c", "index.html", "-o", str(output_path), "--quality", "high"),
            work_dir,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"hyperframes render failed:\n{result.stderr or result.stdout}"
            )
        return output_path

    def check(self, work_dir: Path) -> tuple[bool, list[str]]:
        """Run the runtime's own gate (`hyperframes check --json`).

        Returns (ok, human-readable findings). Non-JSON output degrades to
        the raw text so the caller always gets something actionable.
        """
        result = self._run(self._npx("check", "--json"), work_dir)
        try:
            envelope = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            if result.returncode == 0:
                return True, []
            raw = (result.stdout or "") + (result.stderr or "")
            return False, [f"hyperframes check failed: {raw.strip()}"]

        ok = bool(envelope.get("ok"))
        findings: list[str] = []

        def add(item, *, is_error: bool) -> None:
            if not is_error:
                return  # warnings are advisory; only errors gate the check
            if isinstance(item, dict):
                code = item.get("code", "")
                message = item.get("message", "")
                hint = item.get("fixHint", "")
                parts = [p for p in (code, message, hint) if p]
                findings.append(": ".join(parts) if parts else str(item))
            else:
                findings.append(str(item))

        # Flat shape: top-level errors[]/warnings[].
        for item in envelope.get("errors") or []:
            add(item, is_error=True)
        # Sectioned shape (the real CLI): {lint: {findings: [{severity,...}]}, ...}
        for section in envelope.values():
            if isinstance(section, dict) and isinstance(section.get("findings"), list):
                for item in section["findings"]:
                    severity = item.get("severity") if isinstance(item, dict) else "error"
                    add(item, is_error=severity == "error")

        if not ok and not findings:
            findings.append("hyperframes check reported failure with no findings")
        return ok, findings if not ok else []

    def preview(self, work_dir: Path) -> None:
        subprocess.Popen(self._npx("preview"), cwd=str(work_dir))
