"""Showrunner CLI — AI-powered video generation."""

from __future__ import annotations

from pathlib import Path

import click

from showrunner import __version__
from showrunner.music.cli import music_cli


@click.group()
@click.version_option(version=__version__)
@click.option(
    "--json", "json_output", is_flag=True,
    help="Agent mode: machine-readable JSON on stdout, human logs on stderr. "
         "NDJSON events for create/refine; a single JSON document for listing "
         "commands. Schema documented in README (additive-only contract).",
)
@click.pass_context
def cli(ctx, json_output):
    """Showrunner — AI-powered video generation framework."""
    ctx.ensure_object(dict)
    ctx.obj["json_output"] = json_output


cli.add_command(music_cli)


def _json_flag(f):
    """Per-command `--json` so the flag works both before and after the
    subcommand (`showrunner --json create ...` and
    `showrunner create ... --json`)."""
    return click.option(
        "--json", "json_output", is_flag=True,
        help="Agent mode: machine-readable JSON on stdout (see README).",
    )(f)


def _json_mode(ctx, json_output: bool) -> bool:
    return json_output or bool((ctx.obj or {}).get("json_output"))


def _json_doc(doc: dict) -> str:
    """Single-JSON-document output for listing commands under --json."""
    import json

    return json.dumps(doc, indent=2, default=str)


@cli.command()
@click.argument("topic", required=False)
@click.option("--topic-file", type=click.Path(exists=True), help="Read topic from file")
@click.option("--format", "format_name", default=None, help="Video format")
@click.option("--style", default=None, help="Style preset name")
@click.option("--override", default=None, help="Free-form style overrides")
@click.option("--model", default=None, help="LLM model override")
@click.option(
    "--aspect-ratio",
    default="9:16",
    type=click.Choice(["9:16", "16:9", "1:1", "4:5"]),
)
@click.option("--voice", default="af_heart", help="TTS voice ID")
@click.option("--speed", default=1.0, type=float, help="TTS speed multiplier")
@click.option("--captions", is_flag=True, help="Burn subtitles into video")
@click.option("--watermark", default=None, help="Watermark text overlay")
@click.option("--output", "output_path", type=click.Path(), default=None)
@click.option("--auto-approve", is_flag=True, help="Skip storyboard review")
@click.option("--no-audio", is_flag=True, help="Skip TTS narration")
@click.option("--dry-run", is_flag=True, help="Generate plan only")
@click.option("--preview", is_flag=True, help="Open Remotion Studio")
@click.option("--parallel", is_flag=True, help="Generate scenes concurrently")
@click.option("--storyboard", type=click.Path(exists=True), help="Load existing storyboard JSON")
@click.option("--regen-scene", default=None, help="Regenerate a specific scene")
@click.option("--render-only", is_flag=True, help="Render from existing scenes")
@click.option("--music", default="auto",
              help="Background music: 'auto' (mood-pick from preset), 'none', or a catalog track id.")
@click.option("--music-volume", type=float, default=None,
              help="Override music volume (0.0-1.0). Default comes from the preset.")
@click.option("--music-seed", default=None,
              help="Override the seed used to deterministically pick music. "
                   "Defaults to the topic so the same topic always picks the same track.")
@click.option("--analyze", "analyze_after", is_flag=True,
              help="After a successful render, upload the output for cloud "
                   "analysis (requires `showrunner login`) and print the "
                   "analysis. Analysis problems never fail the render.")
@_json_flag
@click.pass_context
def create(
    ctx,
    topic,
    topic_file,
    format_name,
    style,
    override,
    model,
    aspect_ratio,
    voice,
    speed,
    captions,
    watermark,
    output_path,
    auto_approve,
    no_audio,
    dry_run,
    preview,
    parallel,
    storyboard,
    regen_scene,
    render_only,
    music,
    music_volume,
    music_seed,
    analyze_after,
    json_output,
):
    """Create a video from a topic."""
    from showrunner.cli.json_out import JsonEventStream, write_json_line
    from showrunner.config import load_config
    from showrunner.pipeline import Pipeline
    from showrunner.plan import Plan

    json_mode = _json_mode(ctx, json_output)

    def echo_human(msg: str = "") -> None:
        # In --json mode, stdout is reserved for NDJSON events; human
        # logging moves to stderr.
        click.echo(msg, err=json_mode)

    if topic_file:
        topic = Path(topic_file).read_text().strip()
    if not topic and not storyboard:
        if json_mode:
            write_json_line({
                "event": "error", "stage": "cli",
                "message": "Provide a topic or --storyboard",
            })
            ctx.exit(2)
        raise click.UsageError("Provide a topic or --storyboard")

    config = load_config()

    if model:
        provider_name = config.providers.get("llm", "anthropic")
        if provider_name not in config.provider_config:
            config.provider_config[provider_name] = {}
        config.provider_config[provider_name]["model"] = model

    resolved_format = format_name or config.default_format
    pipeline = Pipeline(format_name=resolved_format, config=config)

    if storyboard:
        plan = Plan.from_json(Path(storyboard).read_text())
        if json_mode:
            write_json_line({
                "event": "plan_ready",
                "title": plan.title,
                "scenes": len(plan.scenes),
                "total_duration": plan.total_duration,
                "plan": plan.to_dict(),
            })
        else:
            click.echo(f"Loaded storyboard: {plan.title} ({len(plan.scenes)} scenes)")
        return

    echo_human(f"Creating video: {topic}")
    echo_human(f"  Style: {style or config.default_style}")
    echo_human(f"  Format: {resolved_format}")
    echo_human()

    if json_mode:
        # Per-scene assets are TSX code for Remotion formats, generated
        # video clips for ai-video. TTS progress always reports "tts".
        stream = JsonEventStream(
            asset_kind="clip" if resolved_format == "ai-video" else "code",
        )
        on_event = stream
    else:
        # Surface the work_dir on a single discoverable line so external
        # hosts (Showrunner Studio, IDE plugins) can capture it via stdout
        # and later call `showrunner refine <work_dir> ...` for surgical
        # scene edits without re-running the full pipeline.
        from showrunner.events import WorkDirReady

        def on_event(ev):
            if isinstance(ev, WorkDirReady):
                click.echo(f"WORKDIR: {ev.work_dir}")

    try:
        result = pipeline.run(
            topic,
            style=style,
            style_override=override,
            output_path=Path(output_path) if output_path else None,
            aspect_ratio=aspect_ratio,
            voice=voice,
            speed=speed,
            captions=captions,
            watermark=watermark,
            parallel=parallel,
            auto_approve=auto_approve,
            no_audio=no_audio,
            dry_run=dry_run,
            preview=preview,
            on_event=on_event,
            music=music,
            music_volume=music_volume,
            music_seed=music_seed,
        )
    except Exception as e:
        if json_mode:
            # Pipeline failures already produced an `error` event via the
            # callback (PipelineFailed); cover everything that failed
            # before/outside the pipeline's own error handling.
            if not stream.error_emitted:
                stream.emit_error(stage="cli", message=str(e))
            ctx.exit(1)
        raise

    if dry_run:
        if json_mode:
            # plan_ready was already emitted; close the stream with a
            # terminal `done` (no output_path/work_dir for a dry run).
            stream.emit_done(extra={"dry_run": True})
        else:
            click.echo(f"\nDry run complete. Plan: {result.title}")
            click.echo(result.to_json())
    elif preview:
        if json_mode:
            stream.emit_done(extra={"preview": True})
        echo_human("\nRemortion Studio opened for preview.")
    else:
        # In json mode the terminal `done` event was emitted by the
        # stream when the pipeline fired RenderCompleted.
        echo_human(f"\nVideo rendered: {result}")
        if analyze_after:
            # The render succeeded and was reported above — analysis
            # problems (not logged in, network, server) exit nonzero but
            # NEVER retroactively fail the render.
            code = _post_render_analyze(result, json_mode)
            if code:
                ctx.exit(code)


@cli.command()
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--output", "output_path", type=click.Path(), default=None)
@click.option("--captions", is_flag=True)
@click.option("--watermark", default=None)
def render(plan_path, output_path, captions, watermark):
    """Render a saved plan to video."""
    click.echo(f"Rendering {plan_path}...")


@cli.command()
@click.argument("work_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.argument("scene_id")
@click.option("--instruction", required=True, help="What to change about this scene")
@click.option("--output", "output_path", type=click.Path(), required=True,
              help="Where to write the refined mp4")
@click.option("--style", default=None,
              help="Style preset to use (defaults to config default_style)")
@_json_flag
@click.pass_context
def refine(ctx, work_dir, scene_id, instruction, output_path, style, json_output):
    """Re-generate a single scene in an existing work_dir and re-render.

    Reuses TTS, sibling scene code, and the composition. Only the named
    scene's TSX is regenerated. ~2-3 min vs ~5-8 min for a full
    `showrunner create`.
    """
    from showrunner.cli.json_out import JsonEventStream
    from showrunner.config import load_config
    from showrunner.pipeline import Pipeline

    json_mode = _json_mode(ctx, json_output)

    config = load_config()
    pipeline = Pipeline(config=config)

    click.echo(f"Refining scene '{scene_id}' in {work_dir}", err=json_mode)
    click.echo(f"  Instruction: {instruction}", err=json_mode)

    if json_mode:
        # refine never emits WorkDirReady (the work_dir is an input), so
        # seed the stream with it for the terminal `done` event.
        on_event = stream = JsonEventStream(work_dir=Path(work_dir))
    else:
        def on_event(ev):
            cls = type(ev).__name__
            click.echo(f"  · {cls}")

    try:
        result = pipeline.refine(
            work_dir=Path(work_dir),
            scene_id=scene_id,
            instruction=instruction,
            output_path=Path(output_path),
            style=style,
            on_event=on_event,
        )
    except Exception as e:
        if json_mode:
            if not stream.error_emitted:
                stream.emit_error(stage="refine", message=str(e))
            ctx.exit(1)
        raise
    click.echo(f"\nRefined video rendered: {result}", err=json_mode)


@cli.command()
@click.argument("work_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--output", "output_path", type=click.Path(), default=None,
              help="Where to write the final mp4 (defaults to ./output/<title>.mp4)")
@_json_flag
@click.pass_context
def resume(ctx, work_dir, output_path, json_output):
    """Resume an interrupted pipeline run from an existing work_dir.

    Reads the per-stage checkpoint files (checkpoint_<stage>.json) written
    by `showrunner create`, skips stages already completed, and picks up
    from the first incomplete one. The assets stage resumes per-scene:
    narration/scene-code/clips that survived the interrupted run are kept.
    Run options (style, voice, music, ...) are replayed from
    showrunner.json so the resumed video matches the original run.
    """
    import json

    from showrunner import checkpoints
    from showrunner.cli.json_out import JsonEventStream, write_json_line
    from showrunner.config import load_config
    from showrunner.pipeline import Pipeline

    json_mode = _json_mode(ctx, json_output)

    work_dir = Path(work_dir)
    meta_path = work_dir / "showrunner.json"
    if not meta_path.exists():
        if json_mode:
            write_json_line({
                "event": "error", "stage": "cli",
                "message": f"{work_dir} is not a showrunner work_dir (no showrunner.json).",
            })
            ctx.exit(2)
        raise click.UsageError(
            f"{work_dir} is not a showrunner work_dir (no showrunner.json). "
            "Only runs started with this version of `showrunner create` are resumable."
        )
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    resolved_format = meta.get("format") or load_config().default_format

    config = load_config()
    pipeline = Pipeline(format_name=resolved_format, config=config)

    click.echo(f"Resuming {work_dir}", err=json_mode)
    for stage in checkpoints.STAGES:
        click.echo(f"  {stage}: {checkpoints.stage_status(work_dir, stage)}", err=json_mode)
    first = checkpoints.first_incomplete_stage(work_dir)
    if first is None:
        click.echo("All stages completed — nothing to resume.", err=json_mode)
    else:
        click.echo(f"Resuming from stage: {first}", err=json_mode)
    click.echo(err=json_mode)

    on_event = None
    stream = None
    if json_mode:
        on_event = stream = JsonEventStream(
            asset_kind="clip" if resolved_format == "ai-video" else "code",
        )

    try:
        result = pipeline.run(
            resume_from=work_dir,
            output_path=Path(output_path) if output_path else None,
            on_event=on_event,
        )
    except Exception as e:
        if json_mode:
            if not stream.error_emitted:
                stream.emit_error(stage="cli", message=str(e))
            ctx.exit(1)
        raise
    click.echo(f"\nVideo rendered: {result}", err=json_mode)


@cli.command()
@click.argument("work_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option(
    "-f", "--format", "fmt",
    type=click.Choice(["otio", "fcpxml", "edl", "aaf"]),
    default="otio",
    help="Output interchange format. Non-otio formats need `pip install showrunner[otio-all]`.",
)
@click.option("-o", "--output", "output_path", type=click.Path(), default=None,
              help="Output file path. Defaults to <work_dir>/timeline.<ext>.")
@click.option("--fps", type=int, default=30, help="Frame rate to encode the timeline at.")
@click.option("--final-mp4", type=click.Path(exists=True), default=None,
              help="Override the final rendered mp4 (faceless-explainer only).")
@_json_flag
@click.pass_context
def export(ctx, work_dir, fmt, output_path, fps, final_mp4, json_output):
    """Export a finished work_dir to OTIO / FCPXML / EDL / AAF.

    The work_dir must contain plan.json and showrunner.json (written by
    `showrunner create`) and the per-scene assets the format produced.
    For faceless-explainer, the final mp4 is split into per-scene clips.
    """
    try:
        from showrunner.exporters import otio as otio_exporter
    except ImportError as e:
        raise click.UsageError(
            "OTIO export requires `pip install showrunner[otio]` "
            f"(or [otio-all] for FCPXML/EDL/AAF). Underlying error: {e}"
        ) from e

    work_dir = Path(work_dir)
    if output_path is None:
        ext = {"otio": "otio", "fcpxml": "fcpxml", "edl": "edl", "aaf": "aaf"}[fmt]
        output_path = work_dir / f"timeline.{ext}"
    adapter = None if fmt == "otio" else fmt

    if final_mp4:
        # Manual override: pre-split then export skips the auto-locate step.
        from showrunner.plan import Plan
        plan = Plan.from_json((work_dir / "plan.json").read_text(encoding="utf-8"))
        otio_exporter.split_final_mp4_by_scenes(
            Path(final_mp4), plan, work_dir / "scenes_split"
        )

    out = otio_exporter.export(work_dir, Path(output_path), adapter=adapter, fps=fps)
    if _json_mode(ctx, json_output):
        click.echo(_json_doc({"output_path": str(out), "format": fmt}))
        return
    click.echo(f"Wrote {out}")


@cli.command()
@_json_flag
@click.pass_context
def formats(ctx, json_output):
    """List available video formats."""
    from showrunner.formats.registry import get_registry

    registry = get_registry()
    entries = [
        {"name": name, "description": registry.get(name).description}
        for name in registry.list()
    ]
    if _json_mode(ctx, json_output):
        click.echo(_json_doc({"formats": entries}))
        return
    for entry in entries:
        click.echo(f"  {entry['name']}: {entry['description']}")


@cli.command()
@_json_flag
@click.pass_context
def styles(ctx, json_output):
    """List available style presets."""
    from showrunner.styles.resolver import list_presets_detailed

    presets = list_presets_detailed()
    if _json_mode(ctx, json_output):
        click.echo(_json_doc({"styles": presets}))
        return
    for preset in presets:
        click.echo(f"  {preset['name']}: {preset['description']}")


@cli.command()
@_json_flag
@click.pass_context
def voices(ctx, json_output):
    """List available TTS voices."""
    from showrunner.providers.tts.kokoro import VOICES

    if _json_mode(ctx, json_output):
        click.echo(_json_doc({"voices": list(VOICES)}))
        return
    for v in VOICES:
        click.echo(f"  {v['id']}: {v['name']} — {v['description']}")


# ── cloud: login / logout / whoami ───────────────────────────────────


def _cloud_import(ctx, json_mode: bool):
    """Import the cloud modules, translating a missing httpx into a
    friendly install hint (cloud is an optional dependency group)."""
    try:
        import httpx  # noqa: F401, PLC0415 — presence check only

        from showrunner import cloud  # noqa: PLC0415
        from showrunner.cloud import auth, client, credentials  # noqa: PLC0415
    except ImportError as e:
        msg = (
            "Cloud commands require the optional cloud dependencies: "
            f"`pip install showrunner[cloud]`. ({e})"
        )
        if json_mode:
            click.echo(_json_doc({"error": "missing_dependency", "message": msg}))
            ctx.exit(2)
        raise click.UsageError(msg) from e
    return cloud, auth, client, credentials


def _resolve_server(server_url: str | None) -> str:
    from showrunner.cloud import resolve_server_url
    from showrunner.config import load_config

    return resolve_server_url(load_config(), override=server_url)


@cli.command()
@click.option("--server", "server_url", default=None,
              help="Cloud server URL (default: cloud.server_url from "
                   ".showrunner.yaml, else the public server).")
@click.option("--no-browser", is_flag=True,
              help="Don't open a browser: print the authorize URL and paste "
                   "the redirect URL/code back (for SSH/headless sessions).")
@_json_flag
@click.pass_context
def login(ctx, server_url, no_browser, json_output):
    """Log in to Showrunner Cloud (OAuth PKCE via your browser)."""
    json_mode = _json_mode(ctx, json_output)
    _, auth, _, credentials = _cloud_import(ctx, json_mode)

    server = _resolve_server(server_url)

    def echo(msg: str = "") -> None:
        click.echo(msg, err=json_mode)

    def prompt(text: str) -> str:
        return click.prompt(text.rstrip(": "), err=json_mode)

    try:
        creds = auth.login(
            server, no_browser=no_browser, echo=echo, prompt=prompt,
        )
    except auth.LoginError as e:
        if json_mode:
            click.echo(_json_doc({"error": "login_failed", "message": str(e)}))
            ctx.exit(1)
        raise click.ClickException(str(e)) from e

    store = credentials.CredentialStore()
    store.save(creds)
    stored_in = store.backend_description()

    if json_mode:
        click.echo(_json_doc({
            "status": "logged_in",
            "server_url": creds.server_url,
            "scopes": creds.scopes,
            "expires_at": creds.expires_at,
            "credentials_stored_in": stored_in,
        }))
        return
    click.echo(f"Logged in to {creds.server_url}")
    if creds.scopes:
        click.echo(f"  Scopes: {creds.scopes}")
    click.echo(f"  Credentials stored in: {stored_in}")


@cli.command()
@click.option("--server", "server_url", default=None, help="Cloud server URL.")
@_json_flag
@click.pass_context
def logout(ctx, server_url, json_output):
    """Log out: revoke the session (best-effort) and clear credentials."""
    json_mode = _json_mode(ctx, json_output)
    _, auth, _, credentials = _cloud_import(ctx, json_mode)

    server = _resolve_server(server_url)
    store = credentials.CredentialStore()
    creds = store.load(server)

    revoked = False
    if creds is not None and creds.source != "env":
        revoked = auth.revoke(creds)
    store.clear(server)

    if json_mode:
        click.echo(_json_doc({
            "status": "logged_out", "server_url": server, "revoked": revoked,
        }))
        return
    click.echo(f"Logged out of {server}")
    if creds is None:
        click.echo("  (no stored credentials were found)")
    elif not revoked:
        click.echo("  (server-side revocation unavailable; local credentials cleared)")


@cli.command()
@click.option("--server", "server_url", default=None, help="Cloud server URL.")
@_json_flag
@click.pass_context
def whoami(ctx, server_url, json_output):
    """Show the logged-in cloud identity and token status."""
    json_mode = _json_mode(ctx, json_output)
    _, _, client_mod, credentials = _cloud_import(ctx, json_mode)

    server = _resolve_server(server_url)
    store = credentials.CredentialStore()
    creds = store.load(server)

    if creds is None:
        if json_mode:
            click.echo(_json_doc({"logged_in": False, "server_url": server}))
        else:
            click.echo(f"Not logged in to {server}. Run `showrunner login`.")
        ctx.exit(1)

    # Best-effort identity check against the API; local token info is
    # still useful when the server or network is unavailable.
    user = None
    api_error = None
    try:
        with client_mod.CloudClient(server, store=store, credentials=creds) as api:
            resp = api.get("/api/v1/me")
            if resp.status_code == 200:
                user = resp.json()
            else:
                api_error = f"HTTP {resp.status_code}"
    except credentials.NotLoggedInError as e:
        if json_mode:
            click.echo(_json_doc({
                "logged_in": False, "server_url": server, "message": str(e),
            }))
        else:
            click.echo(str(e))
        ctx.exit(1)
    except Exception as e:  # network down etc. — degrade to local info
        api_error = str(e)

    doc = {
        "logged_in": True,
        "server_url": server,
        "token_source": creds.source,
        "scopes": creds.scopes,
        "expires_at": creds.expires_at,
        "user": user,
    }
    if api_error:
        doc["api_error"] = api_error
    if json_mode:
        click.echo(_json_doc(doc))
        return
    click.echo(f"Logged in to {server}")
    if user:
        ident = user.get("email") or user.get("name") or user.get("user_id") or user.get("id")
        if ident:
            click.echo(f"  User: {ident}")
    click.echo(f"  Token source: {creds.source}")
    if creds.scopes:
        click.echo(f"  Scopes: {creds.scopes}")
    if api_error:
        click.echo(f"  (could not verify with the server: {api_error})")


# ── cloud: analyze ───────────────────────────────────────────────────


def _analyze_on_event(json_mode: bool):
    """Event callback: NDJSON passthrough in --json, progress prose otherwise."""
    from showrunner.cli.json_out import write_json_line

    last_pct = [-1.0]

    def on_event(doc: dict) -> None:
        if json_mode:
            write_json_line(doc)
            return
        if doc.get("event") == "upload_progress":
            pct = doc.get("pct", 0.0)
            # Avoid drowning the terminal: only whole-percent-ish steps.
            if pct >= 100.0 or pct - last_pct[0] >= 1.0:
                last_pct[0] = pct
                click.echo(f"\r  Uploading: {pct:5.1f}%", nl=(pct >= 100.0))
        elif doc.get("event") == "analysis_pending":
            click.echo(
                f"  Analysis {doc.get('status', 'pending')} — "
                f"next check in {doc.get('retry_after_seconds')}s"
            )

    return on_event


def _run_analyze_flow(
    path: Path,
    *,
    server_url: str | None,
    json_mode: bool,
    output_path: Path | None = None,
    terminal_event: str = "done",
) -> int:
    """Shared by `showrunner analyze` and `create --analyze`.

    Returns a process exit code (0 = success). Never raises: everything
    is rendered as an actionable message (and an `error` event in
    --json) so `create --analyze` can never break a finished render.
    """
    from showrunner.cli.json_out import write_json_line

    def fail(message: str, *, code: int = 1) -> int:
        if json_mode:
            write_json_line({"event": "error", "stage": "analyze", "message": message})
        else:
            click.echo(f"Analysis failed: {message}", err=True)
        return code

    try:
        from showrunner.cloud import analyze as analyze_mod  # noqa: PLC0415
        from showrunner.cloud.client import CloudClient  # noqa: PLC0415
        from showrunner.cloud.credentials import NotLoggedInError  # noqa: PLC0415
    except ImportError as e:
        return fail(
            "cloud analysis requires the optional cloud dependencies: "
            f"`pip install showrunner[cloud]`. ({e})",
            code=2,
        )

    server = _resolve_server(server_url)
    try:
        video_path = analyze_mod.resolve_video_path(Path(path))
    except analyze_mod.AnalyzeError as e:
        return fail(str(e), code=2)

    if not json_mode:
        click.echo(f"Analyzing {video_path} via {server}")

    on_event = _analyze_on_event(json_mode)
    try:
        with CloudClient(server) as client:
            analysis = analyze_mod.upload_and_analyze(
                client, video_path, on_event=on_event,
            )
    except NotLoggedInError as e:
        return fail(f"{e}")
    except analyze_mod.AnalyzeError as e:
        return fail(str(e))
    except Exception as e:  # network and other unexpected failures
        return fail(f"unexpected error during cloud analysis: {e}")

    saved_to = None
    if output_path is not None:
        import json as json_lib  # noqa: PLC0415

        Path(output_path).write_text(
            json_lib.dumps(analysis, indent=2), encoding="utf-8"
        )
        saved_to = str(output_path)

    if json_mode:
        doc = {
            "event": terminal_event,
            "video_path": str(video_path),
            "analysis": analysis,
        }
        if saved_to:
            doc["output_path"] = saved_to
        write_json_line(doc)
    else:
        click.echo("")
        click.echo(analyze_mod.render_analysis(analysis))
        if saved_to:
            click.echo(f"\nRaw analysis saved to: {saved_to}")
    return 0


def _post_render_analyze(rendered_path, json_mode: bool) -> int:
    """`create --analyze` hook: analyze the rendered mp4, never raising.

    The terminal analyze event is `analysis_done` (additive) because the
    render's own `done` event has already closed the create stream.
    """
    try:
        return _run_analyze_flow(
            Path(rendered_path),
            server_url=None,
            json_mode=json_mode,
            terminal_event="analysis_done",
        )
    except Exception as e:  # belt and braces: never break a finished render
        click.echo(f"Analysis failed: {e}", err=True)
        return 1


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--server", "server_url", default=None, help="Cloud server URL.")
@click.option("--output", "output_path", type=click.Path(), default=None,
              help="Save the raw analysis JSON to this file.")
@_json_flag
@click.pass_context
def analyze(ctx, path, server_url, output_path, json_output):
    """Upload a local video for cloud analysis.

    PATH is a video file (mp4/mov/m4v/avi/mkv/webm) or a showrunner
    work_dir — for a work_dir the rendered mp4 is resolved from
    showrunner.json/output conventions. Requires `showrunner login`
    (or SHOWRUNNER_TOKEN).

    Under --json, emits NDJSON events: `upload_progress`,
    `analysis_pending`, then a terminal `done` carrying the full
    analysis payload (or `error`).
    """
    json_mode = _json_mode(ctx, json_output)
    code = _run_analyze_flow(
        Path(path),
        server_url=server_url,
        json_mode=json_mode,
        output_path=Path(output_path) if output_path else None,
    )
    if code:
        ctx.exit(code)


@cli.command()
def init():
    """Create a .showrunner.yaml config file."""
    import yaml

    config_path = Path.cwd() / ".showrunner.yaml"
    if config_path.exists():
        click.echo(f"Config already exists: {config_path}")
        return
    default = {
        "default_format": "faceless-explainer",
        "default_style": "3b1b-dark",
        "providers": {"llm": "anthropic", "tts": "kokoro", "render": "remotion"},
        "anthropic": {"model": "claude-sonnet-4-5-20250929"},
        "kokoro": {"voice": "af_heart", "speed": 1.0},
        "output": {"aspect_ratio": "9:16", "captions": False},
        "repair_attempts": 2,
        # Cloud (login/analyze) server; see `showrunner login --help`.
        "cloud": {"server_url": "https://api.gpt.social"},
    }
    with open(config_path, "w") as f:
        yaml.dump(default, f, default_flow_style=False, sort_keys=False)
    click.echo(f"Created {config_path}")


@cli.command()
@_json_flag
@click.pass_context
def providers(ctx, json_output):
    """List discovered providers (installed vs configured)."""
    from showrunner.config import load_config
    from showrunner.providers.registry import PROVIDER_KINDS, get_registry

    config = load_config()
    if _json_mode(ctx, json_output):
        # Additive-only schema: "providers" keeps the original
        # configured mapping; "installed" adds registry discovery.
        click.echo(_json_doc({
            "providers": dict(config.providers),
            "installed": {kind: get_registry(kind).list() for kind in PROVIDER_KINDS},
        }))
        return
    for kind in PROVIDER_KINDS:
        configured = config.providers.get(kind)
        registry = get_registry(kind)
        installed = registry.list()
        click.echo(f"{kind}:")
        for name in installed:
            marker = "  (configured)" if name == configured else ""
            click.echo(f"  {name}{marker}")
        if configured and configured not in installed:
            click.echo(f"  !! configured provider '{configured}' is not installed")
