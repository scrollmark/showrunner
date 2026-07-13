"""Build the side-by-side judging report for a benchmark run."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Mirrors docs/quality-rubric.md — the 7 craft dimensions, scored 1-5.
RUBRIC_DIMENSIONS = [
    "Typographic hierarchy",
    "Easing & motion quality",
    "Transitions",
    "Audio-visual sync",
    "Layout rhythm & composition",
    "Visual motifs & cohesion",
    "Depth & texture",
]


def _probe(path: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "format=duration:stream=width,height",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    values = [v for v in (result.stdout or "").split() if v]
    meta = {"duration_s": None, "width": None, "height": None}
    try:
        if len(values) >= 3:
            meta["width"], meta["height"] = int(values[0]), int(values[1])
            meta["duration_s"] = round(float(values[2]), 1)
        elif values:
            meta["duration_s"] = round(float(values[0]), 1)
    except ValueError:
        pass
    return meta


def _extract_frames(video: Path, dest: Path, count: int) -> list[Path]:
    if count <= 0:
        return []
    meta = _probe(video)
    duration = meta.get("duration_s") or 0
    if not duration:
        return []
    dest.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(count):
        t = duration * (i + 0.5) / count
        frame = dest / f"frame-{i:02d}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=270:-2", str(frame)],
            capture_output=True, text=True,
        )
        if frame.exists():
            frames.append(frame)
    return frames


def build_report(run_dir: Path, *, frames: int = 5) -> Path:
    run_dir = Path(run_dir)
    run_meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) \
        if (run_dir / "run.json").exists() else {}

    records = []
    for result_path in sorted(run_dir.glob("*/result.json")):
        record = json.loads(result_path.read_text(encoding="utf-8"))
        video = Path(record["output"]) if record.get("output") else None
        if video and video.exists():
            record["media"] = _probe(video)
            frame_paths = _extract_frames(video, result_path.parent / "frames", frames)
            record["frames"] = [str(p.relative_to(run_dir)) for p in frame_paths]
            record["video_rel"] = str(video.relative_to(run_dir))
        else:
            record["media"], record["frames"], record["video_rel"] = {}, [], None
        records.append(record)

    (run_dir / "results.json").write_text(
        json.dumps({"brief": run_meta.get("brief"), "conditions": records}, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path = run_dir / "report.html"
    report_path.write_text(_render_html(run_meta, records), encoding="utf-8")
    return report_path


def _render_html(run_meta: dict, records: list[dict]) -> str:
    brief = (run_meta.get("brief") or "").strip()
    columns = []
    for r in records:
        media = r.get("media") or {}
        video_html = (
            f'<video controls preload="metadata" src="{r["video_rel"]}"></video>'
            if r.get("video_rel")
            else f'<div class="missing">no output ({r.get("status")})</div>'
        )
        frames_html = "".join(f'<img src="{f}" />' for f in r.get("frames", []))
        cost = f"${r['cost_usd']:.2f}" if r.get("cost_usd") is not None else "—"
        turns = r.get("num_turns") if r.get("num_turns") is not None else "—"
        meta_rows = (
            f"<tr><td>status</td><td>{r.get('status')}</td></tr>"
            f"<tr><td>wall time</td><td>{r.get('duration_s', '—')}s</td></tr>"
            f"<tr><td>agent cost</td><td>{cost}</td></tr>"
            f"<tr><td>turns</td><td>{turns}</td></tr>"
            f"<tr><td>video</td><td>{media.get('width', '—')}×{media.get('height', '—')}, "
            f"{media.get('duration_s', '—')}s</td></tr>"
        )
        rubric_rows = "".join(
            f'<tr><td>{dim}</td><td class="score" contenteditable="true"></td></tr>'
            for dim in RUBRIC_DIMENSIONS
        )
        columns.append(f"""
    <div class="col">
      <h2>{r["condition"]}</h2>
      <p class="sub">{r.get("agent")} · toolchain: {r.get("toolchain")}</p>
      {video_html}
      <div class="frames">{frames_html}</div>
      <table class="meta">{meta_rows}</table>
      <h3>Scorecard (1–5)</h3>
      <table class="rubric">{rubric_rows}
        <tr class="total"><td>Total /35</td><td class="score" contenteditable="true"></td></tr>
      </table>
    </div>""")

    return f"""<!doctype html>
<meta charset="utf-8">
<title>showrunner bench report</title>
<style>
  body {{ background:#0b0d14; color:#e8eaf2; font: 15px/1.5 -apple-system, sans-serif;
         margin: 40px; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin: 0 0 2px; }}
  h3 {{ font-size: 13px; text-transform: uppercase; letter-spacing: .08em;
        color:#9aa1b5; margin: 18px 0 6px; }}
  .brief {{ background:#131726; border:1px solid #232a41; border-radius:10px;
            padding:14px 18px; white-space:pre-wrap; margin-bottom:28px; }}
  .grid {{ display:flex; gap:28px; align-items:flex-start; flex-wrap:wrap; }}
  .col {{ flex:1; min-width:320px; max-width:430px; }}
  .sub {{ color:#9aa1b5; margin:0 0 10px; font-size:13px; }}
  video {{ width:100%; border-radius:10px; background:#000; }}
  .missing {{ padding:60px 0; text-align:center; background:#131726;
              border-radius:10px; color:#f2a4a4; }}
  .frames {{ display:flex; gap:4px; margin-top:8px; overflow-x:auto; }}
  .frames img {{ height:88px; border-radius:4px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  td {{ border-bottom:1px solid #1d2338; padding:5px 8px; }}
  td:first-child {{ color:#9aa1b5; }}
  .score {{ text-align:center; background:#131726; min-width:48px; }}
  .total td {{ font-weight:600; border-top:2px solid #232a41; }}
</style>
<h1>showrunner bench — side-by-side</h1>
<div class="brief">{brief}</div>
<div class="grid">{"".join(columns)}
</div>
"""
