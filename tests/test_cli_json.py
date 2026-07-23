"""`--json` agent mode: NDJSON event stream + single-document listings."""

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from showrunner.cli.json_out import JsonEventStream
from showrunner.cli.main import cli
from showrunner.events import (
    NarrationCompleted,
    PipelineCancelled,
    SceneCompleted,
    SceneFailed,
)
from showrunner.plan import Plan, Scene


def _plan() -> Plan:
    return Plan(
        title="Test Video",
        total_duration=10,
        scenes=[
            Scene(id="intro", duration=5, narration="Hello", visual="Title card"),
            Scene(id="outro", duration=5, narration="Bye", visual="Fade out"),
        ],
    )


def _mock_registry(fmt):
    registry = MagicMock()
    registry.get.return_value = fmt
    registry.list.return_value = ["faceless-explainer"]
    return registry


def _mock_format(plan):
    fmt = MagicMock()
    fmt.preferred_render_provider = "remotion"
    fmt.requires_video_provider = False
    fmt.plan.return_value = plan
    fmt.generate_assets.return_value = {
        "has_audio": True, "durations": {}, "width": 1080, "height": 1920,
    }
    return fmt


def _mock_providers(output: Path):
    render = MagicMock()
    render.render.return_value = output
    # Non-dict get_usage() results are skipped by collect_usage.
    return {"llm": MagicMock(), "tts": MagicMock(), "render": render}


def _parse_ndjson(stdout: str) -> list[dict]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    docs = [json.loads(line) for line in lines]  # every line must parse
    assert all("event" in doc for doc in docs)
    return docs


def _run_create_mocked(args, plan=None, plan_raises=None):
    plan = plan or _plan()
    fmt = _mock_format(plan)
    if plan_raises is not None:
        fmt.plan.side_effect = plan_raises
    output = Path("out/video.mp4")
    runner = CliRunner()
    with runner.isolated_filesystem():
        with patch("showrunner.pipeline.get_registry", return_value=_mock_registry(fmt)), \
             patch("showrunner.pipeline.Pipeline._create_providers",
                   return_value=_mock_providers(output)):
            result = runner.invoke(cli, args, catch_exceptions=False)
    return result


# ── create: NDJSON stream ────────────────────────────────────────────────


def test_create_json_ndjson_stream_and_done():
    result = _run_create_mocked(
        ["create", "My topic", "--json", "--music", "none", "--output", "out/video.mp4"],
    )
    assert result.exit_code == 0
    docs = _parse_ndjson(result.stdout)
    events = [d["event"] for d in docs]

    assert "plan_ready" in events
    assert "work_dir_ready" in events
    assert "stage_started" in events
    assert events[-1] == "done"

    plan_ready = next(d for d in docs if d["event"] == "plan_ready")
    assert plan_ready["title"] == "Test Video"
    assert plan_ready["scenes"] == 2
    assert plan_ready["total_duration"] == 10

    work_dir_ready = next(d for d in docs if d["event"] == "work_dir_ready")
    done = next(d for d in docs if d["event"] == "done")
    assert done["output_path"].endswith("video.mp4")
    assert done["work_dir"] == work_dir_ready["work_dir"]

    # Human logs went to stderr, not stdout.
    assert "Creating video" in result.stderr
    assert "Creating video" not in result.stdout


def test_create_storyboard_runs_full_pipeline_not_just_plan():
    """`--storyboard` must reach assets/compose/render like a topic-driven
    run, not print plan_ready and stop (the bug this test guards against:
    the CLI used to `return` right after loading the plan)."""
    plan = _plan()
    fmt = _mock_format(plan)
    output = Path("out/video.mp4")
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("storyboard.json").write_text(plan.to_json())
        with patch("showrunner.pipeline.get_registry", return_value=_mock_registry(fmt)), \
             patch("showrunner.pipeline.Pipeline._create_providers",
                   return_value=_mock_providers(output)):
            result = runner.invoke(
                cli,
                ["create", "--format", "faceless-explainer", "--storyboard", "storyboard.json",
                 "--json", "--music", "none", "--output", "out/video.mp4"],
                catch_exceptions=False,
            )

    assert result.exit_code == 0
    fmt.plan.assert_not_called()
    docs = _parse_ndjson(result.stdout)
    events = [d["event"] for d in docs]
    assert "plan_ready" in events
    assert "work_dir_ready" in events
    assert events[-1] == "done"


def test_create_json_flag_before_subcommand():
    result = _run_create_mocked(
        ["--json", "create", "My topic", "--music", "none", "--output", "out/video.mp4"],
    )
    assert result.exit_code == 0
    docs = _parse_ndjson(result.stdout)
    assert docs[-1]["event"] == "done"


def test_create_json_error_event_and_nonzero_exit():
    result = _run_create_mocked(
        ["create", "My topic", "--json", "--music", "none"],
        plan_raises=RuntimeError("planner exploded"),
    )
    assert result.exit_code != 0
    docs = _parse_ndjson(result.stdout)
    error = docs[-1]
    assert error["event"] == "error"
    assert "planner exploded" in error["message"]


def test_create_json_usage_error_is_json_too():
    runner = CliRunner()
    result = runner.invoke(cli, ["create", "--json"])
    assert result.exit_code != 0
    docs = _parse_ndjson(result.stdout)
    assert docs[-1]["event"] == "error"
    assert "topic" in docs[-1]["message"]


def test_create_json_dry_run_emits_plan_and_done():
    fmt = _mock_format(_plan())
    runner = CliRunner()
    with runner.isolated_filesystem():
        with patch("showrunner.pipeline.get_registry", return_value=_mock_registry(fmt)), \
             patch("showrunner.pipeline.Pipeline._create_llm", return_value=MagicMock()):
            result = runner.invoke(
                cli, ["create", "My topic", "--json", "--dry-run"],
                catch_exceptions=False,
            )
    assert result.exit_code == 0
    docs = _parse_ndjson(result.stdout)
    plan_ready = next(d for d in docs if d["event"] == "plan_ready")
    assert plan_ready["plan"]["title"] == "Test Video"
    assert docs[-1]["event"] == "done"
    assert docs[-1]["dry_run"] is True
    assert docs[-1]["output_path"] is None


def test_create_human_mode_keeps_workdir_line():
    result = _run_create_mocked(
        ["create", "My topic", "--music", "none", "--output", "out/video.mp4"],
    )
    assert result.exit_code == 0
    workdir_lines = [
        line for line in result.stdout.splitlines() if line.startswith("WORKDIR: ")
    ]
    assert len(workdir_lines) == 1


# ── refine: NDJSON stream ────────────────────────────────────────────────


def test_refine_json_error_event_and_nonzero_exit(tmp_path):
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["refine", str(tmp_path), "no_such_scene",
         "--instruction", "make it pop", "--output", str(tmp_path / "o.mp4"),
         "--json"],
    )
    assert result.exit_code != 0
    docs = _parse_ndjson(result.stdout)
    assert docs[-1]["event"] == "error"
    # Everything on stdout parsed as JSON (asserted in _parse_ndjson).


# ── listing commands: single JSON document ───────────────────────────────


def test_formats_json_single_document():
    fmt = MagicMock()
    fmt.description = "Remotion explainers"
    with patch("showrunner.formats.registry.get_registry",
               return_value=_mock_registry(fmt)):
        runner = CliRunner()
        result = runner.invoke(cli, ["formats", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["formats"] == [
        {"name": "faceless-explainer", "description": "Remotion explainers"}
    ]


def test_styles_json_single_document():
    runner = CliRunner()
    result = runner.invoke(cli, ["styles", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    names = [p["name"] for p in doc["styles"]]
    assert "3b1b-dark" in names


def test_voices_json_single_document():
    fake = types.ModuleType("showrunner.providers.tts.kokoro")
    fake.VOICES = [{"id": "af_heart", "name": "Heart", "description": "Warm"}]
    with patch.dict(sys.modules, {"showrunner.providers.tts.kokoro": fake}):
        runner = CliRunner()
        result = runner.invoke(cli, ["voices", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["voices"][0]["id"] == "af_heart"


def test_providers_json_single_document():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["providers", "--json"], catch_exceptions=False)
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["providers"]["llm"] == "anthropic"


# ── JsonEventStream unit mapping ─────────────────────────────────────────


def _capture_doc(stream, event, capsys) -> dict:
    stream(event)
    return json.loads(capsys.readouterr().out.strip())


def test_stream_narration_maps_to_tts_asset_progress(capsys):
    doc = _capture_doc(
        JsonEventStream(),
        NarrationCompleted(scene_id="intro", duration_seconds=4.2),
        capsys,
    )
    assert doc == {
        "event": "asset_progress", "scene_id": "intro", "kind": "tts",
        "status": "completed", "duration_seconds": 4.2,
    }


def test_stream_scene_kind_follows_format(capsys):
    doc = _capture_doc(
        JsonEventStream(asset_kind="clip"),
        SceneCompleted(scene_id="s1", index=1, total=3),
        capsys,
    )
    assert doc["kind"] == "clip"
    assert doc["event"] == "asset_progress"
    assert doc["status"] == "completed"


def test_stream_scene_failed_and_cancelled(capsys):
    stream = JsonEventStream()
    doc = _capture_doc(stream, SceneFailed(scene_id="s1", error="tsc failed"), capsys)
    assert doc == {"event": "scene_failed", "scene_id": "s1", "error": "tsc failed"}

    doc = _capture_doc(stream, PipelineCancelled(work_dir=Path("/tmp/wd")), capsys)
    assert doc == {"event": "cancelled", "work_dir": "/tmp/wd"}


def test_stream_ignores_unknown_events(capsys):
    class FutureEvent:
        pass

    stream = JsonEventStream()
    stream(FutureEvent())
    assert capsys.readouterr().out == ""
