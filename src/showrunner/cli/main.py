"""Showrunner CLI — AI-powered video generation."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

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
                   "post_id — fetch the result later with `showrunner "
                   "analyze --id <id>`. Never polls; analysis problems "
                   "never fail the render.")
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
@click.option("--with-password", "with_password", is_flag=True,
              help="Log in with email + password (Firebase) — the flow that "
                   "works against the production server today. Without this "
                   "flag, login uses the browser OAuth PKCE flow, which "
                   "activates once the server's OAuth chain deploys "
                   "(scrollmark/showrunner#55). A default method can also be "
                   "set via cloud.auth_method in .showrunner.yaml.")
@click.option("--no-browser", is_flag=True,
              help="OAuth flow only — don't open a browser: print the "
                   "authorize URL and paste the redirect URL/code back "
                   "(for SSH/headless sessions).")
@_json_flag
@click.pass_context
def login(ctx, server_url, with_password, no_browser, json_output):
    """Log in to Showrunner Cloud (OAuth via browser, or email+password).

    Today's working path against production is `showrunner login
    --with-password`; plain `showrunner login` (browser OAuth) activates
    when the backend OAuth chain ships.
    """
    json_mode = _json_mode(ctx, json_output)
    _, auth, _, credentials = _cloud_import(ctx, json_mode)

    from showrunner.cloud import (  # noqa: PLC0415
        firebase,
        resolve_auth_method,
        resolve_firebase_api_key,
    )
    from showrunner.config import load_config  # noqa: PLC0415

    config = load_config()
    server = _resolve_server(server_url)
    method = resolve_auth_method(
        config, override="firebase" if with_password else None
    )

    def fail(e: Exception) -> None:
        message = str(e)
        if getattr(e, "unknown_client", False):
            message += (
                "\n\nThe server does not recognize the CLI's OAuth client — "
                "its OAuth login chain is probably not deployed yet. Log in "
                "with email + password instead:\n\n"
                "  showrunner login --with-password"
            )
        if json_mode:
            click.echo(_json_doc({"error": "login_failed", "message": message}))
            ctx.exit(1)
        raise click.ClickException(message) from e

    def echo(msg: str = "") -> None:
        click.echo(msg, err=json_mode)

    def prompt(text: str) -> str:
        return click.prompt(text.rstrip(": "), err=json_mode)

    if method == "firebase":
        echo(f"Logging in to {server} with email and password.")
        email = click.prompt("Email", err=json_mode)
        password = click.prompt("Password", hide_input=True, err=json_mode)
        try:
            creds = firebase.sign_in(
                server, email, password,
                api_key=resolve_firebase_api_key(config),
            )
        except firebase.FirebaseLoginError as e:
            return fail(e)
    else:
        try:
            creds = auth.login(
                server, no_browser=no_browser, echo=echo, prompt=prompt,
            )
        except auth.LoginError as e:
            return fail(e)

    store = credentials.CredentialStore()
    store.save(creds)
    stored_in = store.backend_description()

    if json_mode:
        click.echo(_json_doc({
            "status": "logged_in",
            "server_url": creds.server_url,
            "method": creds.method,
            "scopes": creds.scopes,
            "expires_at": creds.expires_at,
            "credentials_stored_in": stored_in,
        }))
        return
    click.echo(f"Logged in to {creds.server_url}")
    click.echo(f"  Method: {creds.method}")
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
    if creds is not None and creds.source != "env" and creds.method != "firebase":
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
    elif creds.method == "firebase":
        click.echo("  (Firebase session: local credentials cleared)")
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

    if creds.method == "firebase":
        # The server-side identity endpoint (/api/v1/me) is part of the
        # OAuth path — for firebase sessions, decode the ID token's
        # claims locally instead (display only; no signature check —
        # the SERVER verifies tokens on every request).
        import time  # noqa: PLC0415

        from showrunner.cloud import firebase  # noqa: PLC0415

        claims = {}
        try:
            claims = firebase.decode_id_token(creds.access_token)
        except firebase.FirebaseLoginError:
            pass
        user_id = claims.get("user_id") or claims.get("sub")
        email = claims.get("email")
        doc = {
            "logged_in": True,
            "server_url": server,
            "method": "firebase",
            "token_source": creds.source,
            "user_id": user_id,
            "email": email,
            "expires_at": creds.expires_at,
            "identity_source": "local_token",
        }
        if json_mode:
            click.echo(_json_doc(doc))
            return
        click.echo(f"Logged in to {server}")
        if email:
            click.echo(f"  User: {email}")
        if user_id:
            click.echo(f"  User ID: {user_id}")
        click.echo("  Method: firebase")
        click.echo(f"  Token source: {creds.source}")
        if creds.expires_at:
            remaining = int(creds.expires_at - time.time())
            click.echo(f"  Token expires in: ~{max(remaining, 0)}s")
        click.echo(
            "  (identity decoded locally from the stored ID token; "
            "not verified with the server)"
        )
        return

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


# ── cloud: analyze (async upload / get / list) ───────────────────────


def _analyze_on_event(json_mode: bool, *, verbose: bool = False):
    """Event callback: NDJSON passthrough in --json; otherwise progress
    prose on STDERR under --verbose, and silence by default.

    Human mode is quiet-by-default so stdout carries only the payload
    (`showrunner analyze --id X --transcript > file` stays clean);
    --verbose re-enables the progress/status lines, on stderr only.
    """
    from showrunner.cli.json_out import write_json_line

    last_pct = [-1.0]

    def on_event(doc: dict) -> None:
        if json_mode:
            write_json_line(doc)
            return
        if not verbose:
            return
        if doc.get("event") == "upload_progress":
            pct = doc.get("pct", 0.0)
            # Avoid drowning the terminal: only whole-percent-ish steps.
            if pct >= 100.0 or pct - last_pct[0] >= 1.0:
                last_pct[0] = pct
                click.echo(
                    f"\r  Uploading: {pct:5.1f}%", nl=(pct >= 100.0), err=True
                )
        elif doc.get("event") == "analysis_pending":
            click.echo(
                f"  Analysis {doc.get('status', 'pending')} — "
                f"next check in {doc.get('retry_after_seconds')}s",
                err=True,
            )
        elif doc.get("event") == "upload_retry":
            last_pct[0] = -1.0  # the retry restarts the progress line
            click.echo(
                f"\n  Upload interrupted ({doc.get('reason')}) — retrying "
                f"with the same id (attempt {doc.get('attempt')}/"
                f"{doc.get('max_attempts')}) in "
                f"{doc.get('retry_after_seconds')}s",
                err=True,
            )

    return on_event


def _fmt_age(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def _write_output(output_path: Path, doc: dict, sections, json_mode: bool) -> None:
    """--output FILE: write the same content the terminal shows."""
    content = _json_doc(doc) if json_mode else _render_sections(sections)
    Path(output_path).write_text(content + "\n", encoding="utf-8")


def _render_sections(sections) -> str:
    """Human rendering: bare text for one artifact, titled sections for
    several (so single-artifact output stays pipeable, e.g. --video-url)."""
    if len(sections) == 1:
        return sections[0][1]
    blocks = [f"{title}\n{'-' * len(title)}\n{text}" for title, text in sections]
    return "\n\n".join(blocks)


def _collect_artifacts(client, analyze_mod, post_id: str, analysis: dict, wants: dict):
    """Build (json_doc, human_sections) for the requested artifacts.

    `wants` maps artifact name -> requested?; "video" carries None (not
    requested), "" (download with the default filename), or a dest path.
    Caption/video artifacts call the server and may raise AnalyzeError.
    """
    import json as json_lib  # noqa: PLC0415

    from showrunner.cloud import ledger  # noqa: PLC0415

    doc: dict = {"post_id": post_id, "status": "ready"}
    sections: list[tuple[str, str]] = []
    if wants.get("report"):
        text = analyze_mod.render_analysis(analysis)
        doc["report"] = text
        sections.append(("Report", text))
    if wants.get("full"):
        doc["full"] = analysis
        sections.append(("Full analysis", json_lib.dumps(analysis, indent=2)))
    if wants.get("transcript"):
        doc["transcript"] = analyze_mod.transcript_segments(analysis)
        sections.append(("Transcript", analyze_mod.render_transcript(analysis)))
    if wants.get("overlays"):
        doc["overlays"] = analyze_mod.overlay_segments(analysis)
        sections.append(("Text overlays", analyze_mod.render_overlays(analysis)))
    if wants.get("scenes"):
        doc["scenes"] = analysis.get("scenes") or []
        sections.append(("Scenes", analyze_mod.render_scenes(analysis)))
    if wants.get("caption"):
        caption = analyze_mod.generate_caption(client, post_id)
        doc["caption"] = caption
        sections.append(("Caption", caption))
    if wants.get("video_url"):
        url = analyze_mod.get_video_url(client, post_id)
        doc["video_url"] = url
        sections.append(("Video URL", url))
    if wants.get("video") is not None:
        dest = wants["video"]
        if not dest:
            # Default filename: the original upload's basename (from the
            # local ledger), else <post_id>.mp4.
            entry = next(
                (e for e in reversed(ledger.read_entries())
                 if e.get("post_id") == post_id),
                None,
            )
            dest = (
                Path(entry["file"]).name
                if entry and entry.get("file") else f"{post_id}.mp4"
            )
        dest = analyze_mod.download_video(client, post_id, Path(dest))
        doc["video"] = str(dest)
        # The payload went to the file; the confirmation is a notice, not
        # output — stderr, per the clean-stdout contract.
        click.echo(f"Downloaded to {dest}", err=True)
    return doc, sections


def _submit_analyze(
    path: Path,
    *,
    server_url: str | None,
    json_mode: bool,
    sync: bool = False,
    output_path: Path | None = None,
    timeout: float | None = None,
    bare_id: bool = False,
    wants: dict | None = None,
    if_duplicate: str = "warn",
    verbose: bool = False,
) -> int:
    """Shared by `showrunner analyze <path>` and `create --analyze`.

    Mints a UUIDv4 post_id client-side, uploads the video under it
    (transient failures retry with the same id — no duplicate drafts),
    records the attempt and the completed upload in the local ledger
    (~/.showrunner/analyses.jsonl), and prints the post_id; polls for
    the analysis (then renders the `wants` artifacts) only when `sync`.

    OUTPUT CONTRACT (human mode): stdout carries only the payload —
    with `bare_id` the bare post_id (so `id=$(showrunner analyze
    clip.mp4)` and redirection stay clean), with `sync` the rendered
    artifacts. Progress/status chatter is silent by default; `verbose`
    re-enables it, on STDERR only. Warnings that matter (duplicate
    warning, resumed-upload notice) always go to stderr; errors stay
    on stderr with their exit codes.

    `if_duplicate` governs what happens when the ledger shows the same
    sha256 uploaded within ~24h: "warn" (default) warns and proceeds,
    "reuse" prints the prior post_id WITHOUT uploading (exit 0),
    "fail" refuses with exit 3.

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
        from showrunner.cloud import ledger  # noqa: PLC0415
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

    def note(msg: str) -> None:
        """Verbose-only status chatter — STDERR, never the payload."""
        if verbose and not json_mode:
            click.echo(msg, err=True)

    note(f"Analyzing {video_path} via {server}")

    # Duplicate detection: same bytes uploaded recently. --if-duplicate
    # decides: warn (default) proceeds after a gentle warning, reuse
    # returns the prior post_id without uploading, fail refuses (exit
    # 3). Ledger problems never block an upload.
    sha256 = size_bytes = None
    duplicate = pending = None
    try:
        sha256 = ledger.sha256_file(video_path)
        size_bytes = video_path.stat().st_size
        duplicate = ledger.find_recent_duplicate(sha256)
        pending = ledger.find_pending_upload(sha256)
    except OSError:
        pass
    if duplicate is not None:
        prior_id = duplicate.get("post_id")
        prior_at = duplicate.get("uploaded_at")
        if if_duplicate == "fail":
            return fail(
                f"this exact file was already uploaded as {prior_id} "
                f"({prior_at}) and --if-duplicate fail refuses to upload "
                "it again. Fetch the existing analysis with `showrunner "
                f"analyze --id {prior_id}`, or re-run with --if-duplicate "
                "warn to upload anyway.",
                code=3,
            )
        if if_duplicate == "reuse":
            if json_mode:
                write_json_line({
                    "event": "submitted",
                    "deduped": True,
                    **duplicate,
                    "video_path": str(video_path),
                })
            elif bare_id:
                click.echo(
                    f"Reusing prior upload {prior_id} ({prior_at}) — no "
                    "upload needed. Fetch the analysis with: "
                    f"showrunner analyze --id {prior_id}",
                    err=True,  # matters, so not verbose-gated
                )
                click.echo(prior_id)  # the only stdout line
            else:
                click.echo(f"Reusing prior upload: {prior_id} ({prior_at})")
                click.echo(
                    "  Fetch the analysis with: "
                    f"showrunner analyze --id {prior_id}"
                )
            return 0
        if json_mode:
            write_json_line({
                "event": "duplicate_warning",
                "sha256": sha256,
                "prior_post_id": prior_id,
                "prior_uploaded_at": prior_at,
            })
        else:
            click.echo(
                f"Note: this exact file was already uploaded as "
                f"{prior_id} ({prior_at}) — "
                f"`showrunner analyze --id {prior_id}` may "
                "already have your analysis. Uploading again anyway.",
                err=True,
            )

    # Idempotency id: reuse the id of an interrupted upload of the same
    # bytes (recorded as a "pending" ledger line), else mint a fresh
    # UUIDv4. Retrying with the same id can never duplicate drafts.
    minted = None
    if pending is not None and analyze_mod.is_valid_post_id(
        pending.get("post_id")
    ):
        minted = pending["post_id"]
        if json_mode:
            write_json_line({"event": "upload_resume", "post_id": minted})
        else:
            click.echo(
                f"Resuming interrupted upload {minted} (same file, "
                "same id).",
                err=True,  # matters, so not verbose-gated
            )
    if minted is None:
        minted = str(uuid4())

    on_event = _analyze_on_event(json_mode, verbose=verbose)
    try:
        with CloudClient(server) as client:
            if sha256 is not None:
                # Record the attempt BEFORE the bytes move so an
                # interrupted upload can be retried with the same id.
                ledger.record_upload(
                    post_id=minted,
                    file=video_path,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    server=server,
                    upload_status="pending",
                )
            post_id = analyze_mod.upload(
                client, video_path, post_id=minted, on_event=on_event,
            )
            if sha256 is not None:
                ledger.record_upload(
                    post_id=post_id,
                    file=video_path,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    server=server,
                    upload_status="uploaded",
                )
            if not sync:
                if json_mode:
                    write_json_line({
                        "event": "submitted",
                        "post_id": post_id,
                        "video_path": str(video_path),
                        "deduped": False,
                    })
                elif bare_id:
                    note(
                        "Uploaded. Fetch the analysis later with: "
                        f"showrunner analyze --id {post_id}"
                    )
                    click.echo(post_id)  # the only stdout line
                else:
                    click.echo(f"Analysis submitted: {post_id}")
                    click.echo(
                        "  Fetch it later with: "
                        f"showrunner analyze --id {post_id}"
                    )
                return 0
            analysis = analyze_mod.poll_analysis(
                client,
                post_id,
                on_event=on_event,
                max_wait_seconds=(
                    timeout if timeout is not None
                    else analyze_mod.DEFAULT_MAX_WAIT_SECONDS
                ),
            )
            doc, sections = _collect_artifacts(
                client, analyze_mod, post_id, analysis,
                wants or {"report": True},
            )
    except NotLoggedInError as e:
        return fail(f"{e}")
    except analyze_mod.AnalyzeError as e:
        return fail(str(e))
    except Exception as e:  # network and other unexpected failures
        return fail(f"unexpected error during cloud analysis: {e}")

    if json_mode:
        write_json_line({
            "event": "done",
            "video_path": str(video_path),
            "analysis": analysis,  # kept for the additive NDJSON contract
            **doc,
        })
    else:
        # Payload only on stdout — no leading blank line, so redirects
        # capture exactly the artifact content.
        click.echo(_render_sections(sections))
    if output_path is not None:
        _write_output(output_path, doc, sections, json_mode)
        if not json_mode:
            click.echo(f"\nSaved to: {output_path}", err=True)
    return 0


def _fetch_analyze_result(
    post_id: str,
    *,
    server_url: str | None,
    json_mode: bool,
    sync: bool,
    timeout: float,
    wants: dict,
    output_path: Path | None,
    verbose: bool = False,
) -> int:
    """The --id flow: one check (or --sync poll), then render artifacts.

    Human mode is quiet-by-default: stdout carries exactly the rendered
    artifact content (safe to redirect); polling status lines appear
    only under `verbose`, on stderr. Errors stay on stderr.

    Exit codes: 0 ready, 1 real error / terminal failed analysis,
    2 not ready yet (including a --sync timeout). In --json prints ONE
    object: {"post_id", "status", plus the requested artifact keys}.
    """

    def fail(doc: dict, message: str, *, code: int = 1) -> int:
        if json_mode:
            click.echo(_json_doc(doc))
        else:
            click.echo(message, err=True)
        return code

    try:
        from showrunner.cloud import analyze as analyze_mod  # noqa: PLC0415
        from showrunner.cloud.client import CloudClient  # noqa: PLC0415
        from showrunner.cloud.credentials import NotLoggedInError  # noqa: PLC0415
    except ImportError as e:
        msg = (
            "cloud analysis requires the optional cloud dependencies: "
            f"`pip install showrunner[cloud]`. ({e})"
        )
        return fail({"post_id": post_id, "status": "error", "message": msg}, msg)

    server = _resolve_server(server_url)
    on_event = (
        _analyze_on_event(False, verbose=verbose) if not json_mode else None
    )

    try:
        with CloudClient(server) as client:
            analysis = analyze_mod.check_analysis(client, post_id)
            if analysis is None and sync:
                analysis = analyze_mod.poll_analysis(
                    client, post_id, on_event=on_event, max_wait_seconds=timeout,
                )
            if analysis is None:
                return fail(
                    {"post_id": post_id, "status": "pending"},
                    f"Analysis for {post_id} is not ready yet — try again "
                    "shortly, or wait for it with --sync.",
                    code=2,
                )
            doc, sections = _collect_artifacts(
                client, analyze_mod, post_id, analysis, wants,
            )
    except NotLoggedInError as e:
        return fail(
            {"post_id": post_id, "status": "error", "message": str(e)}, str(e)
        )
    except analyze_mod.AnalysisTimeout as e:
        return fail(
            {"post_id": post_id, "status": "pending", "message": str(e)},
            str(e), code=2,
        )
    except analyze_mod.AnalysisFailed as e:
        return fail(
            {"post_id": post_id, "status": "failed", "failure_reason": e.reason},
            f"Analysis failed: {e.reason}",
        )
    except analyze_mod.AnalyzeError as e:
        return fail(
            {"post_id": post_id, "status": "error", "message": str(e)}, str(e)
        )
    except Exception as e:  # network and other unexpected failures
        msg = f"unexpected error fetching the analysis: {e}"
        return fail({"post_id": post_id, "status": "error", "message": msg}, msg)

    if json_mode:
        click.echo(_json_doc(doc))
    else:
        click.echo(_render_sections(sections))
    if output_path is not None:
        _write_output(output_path, doc, sections, json_mode)
        if not json_mode:
            click.echo(f"Saved to: {output_path}", err=True)
    return 0


#: Status vocabulary mapping for `showrunner list --status`. Anything
#: outside these sets derives to None (unknown) — never faked.
_DONE_STATUSES = {"done", "completed", "complete", "ready", "analyzed",
                  "succeeded", "success"}
_PENDING_STATUSES = {"pending", "processing", "in_progress", "queued",
                     "running"}


def _derive_status(row: dict) -> str | None:
    """Best-effort analysis status from a listing row; None when unknown."""
    raw = row.get("analysis_status") or row.get("status")
    if isinstance(raw, str):
        lowered = raw.lower()
        if lowered in _DONE_STATUSES:
            return "done"
        if lowered in _PENDING_STATUSES:
            return "pending"
        if lowered == "failed":
            return "failed"
        return None
    if row.get("analysis"):
        return "done"
    return None


def _iso_age(raw, now: float) -> str | None:
    """Relative age from an ISO timestamp string, or None."""
    from showrunner.cloud import ledger  # noqa: PLC0415

    if not isinstance(raw, str):
        return None
    ts = ledger.parse_uploaded_at({"uploaded_at": raw.replace("Z", "+00:00")})
    if ts is None:
        return None
    return _fmt_age(now - ts)


def _list_local(json_mode: bool, limit: int, status_filter: str | None) -> None:
    """`showrunner list --local`: the ledger view, newest first.

    Uses the latest-wins view: duplicate ledger lines for the same
    post_id (pending attempt + completed upload) collapse to one row.
    """
    import time as time_mod  # noqa: PLC0415

    from showrunner.cloud import ledger  # noqa: PLC0415

    entries = ledger.latest_entries()
    entries.sort(key=lambda e: ledger.parse_uploaded_at(e) or 0.0, reverse=True)
    if status_filter:
        # Ledger records carry no analysis status (unknown never matches).
        entries = [e for e in entries if _derive_status(e) == status_filter]
    if limit and limit > 0:
        entries = entries[:limit]
    if json_mode:
        click.echo(_json_doc({"analyses": entries}))
        return
    if not entries:
        click.echo(
            "No recorded uploads — `showrunner analyze <path>` records each "
            "upload in the local ledger."
            + (" (Note: --status never matches ledger rows: their analysis "
               "status is unknown locally.)" if status_filter else "")
        )
        return
    now = time_mod.time()
    for entry in entries:
        ts = ledger.parse_uploaded_at(entry)
        age = _fmt_age(now - ts) if ts is not None else "?"
        status = _derive_status(entry) or "-"
        click.echo(
            f"{entry['post_id']}  {age:>8}  {status:>8}  "
            f"{entry.get('file', '?')}  ({entry.get('server', '?')})"
        )


def _post_render_analyze(rendered_path, json_mode: bool) -> int:
    """`create --analyze` hook: submit the rendered mp4, never raising.

    Async only: uploads, prints the post_id, appends to the local
    ledger — it NEVER polls, and it NEVER fails the render (a nonzero
    return only marks the analyze step; the video is already on disk
    and reported). In --json, the NDJSON gains upload events plus a
    terminal `submitted` event after the render's own `done`.
    """
    try:
        return _submit_analyze(
            Path(rendered_path), server_url=None, json_mode=json_mode,
        )
    except Exception as e:  # belt and braces: never break a finished render
        click.echo(f"Analysis failed: {e}", err=True)
        return 1


@cli.command()
@click.argument("path", required=False, type=click.Path(exists=True))
@click.option("--id", "post_id", default=None, metavar="ID",
              help="Operate on an existing analysis id (minted by a previous "
                   "upload; see `showrunner list`) instead of uploading.")
@click.option("--server", "server_url", default=None, help="Cloud server URL.")
@click.option("--sync", is_flag=True,
              help="Wait until the analysis is ready: with a PATH, upload and "
                   "poll in one shot; with --id, poll instead of a single "
                   "check.")
@click.option("--timeout", type=float, default=600.0, show_default=True,
              help="--sync only: give up polling after this many seconds "
                   "(exits 2 if still pending).")
@click.option("--report", is_flag=True,
              help="Artifact: human-readable analysis summary (the default "
                   "when no artifact flag is given).")
@click.option("--full", is_flag=True,
              help="Artifact: the complete raw analysis JSON.")
@click.option("--transcript", is_flag=True,
              help="Artifact: the spoken script — plain text in human mode, "
                   "time-coded transcript_segments under --json.")
@click.option("--overlays", is_flag=True,
              help="Artifact: on-screen text (text_overlay_segments).")
@click.option("--scenes", is_flag=True,
              help="Artifact: the scene breakdown.")
@click.option("--caption", is_flag=True,
              help="Artifact: generate and print a social caption. Note: "
                   "generated server-side anew on EVERY call (results may "
                   "differ between calls).")
@click.option("--video", "video_dl", is_flag=False, flag_value="",
              default=None, metavar="[FILE]",
              help="Artifact: download the stored video to FILE (default "
                   "filename: the original upload's name from the ledger, "
                   "else <id>.mp4).")
@click.option("--video-url", "video_url", is_flag=True,
              help="Artifact: print the signed download URL for the stored "
                   "video.")
@click.option("--output", "output_path", type=click.Path(), default=None,
              help="Also write the shown result to this file.")
@click.option("--if-duplicate", "if_duplicate",
              type=click.Choice(["warn", "reuse", "fail"]), default="warn",
              show_default=True,
              help="Uploads only: what to do when the ledger shows these "
                   "exact bytes (same sha256) uploaded within ~24h. warn: "
                   "warn on stderr and upload anyway. reuse: print the "
                   "prior post_id and skip the upload (exit 0). fail: "
                   "refuse (exit 3).")
@click.option("--verbose", is_flag=True,
              help="Show progress/status lines (upload %, retries, "
                   "polling) on stderr. Default output is quiet: stdout "
                   "carries only the payload, safe to redirect.")
@_json_flag
@click.pass_context
def analyze(ctx, path, post_id, server_url, sync, timeout,
            report, full, transcript, overlays, scenes, caption, video_dl,
            video_url, output_path, if_duplicate, verbose, json_output):
    """Upload a video for cloud analysis; fetch results and artifacts.

    Exactly one source: a PATH to upload (a video file — mp4/mov/m4v/
    avi/mkv/webm — or a showrunner work_dir, whose rendered mp4 is
    resolved automatically), XOR --id ID for an already-uploaded
    analysis. Requires `showrunner login` (or SHOWRUNNER_TOKEN). Use
    `showrunner list` to find previous uploads.

    \b
      showrunner analyze clip.mp4              upload; print the post_id
      showrunner analyze clip.mp4 --sync       upload and wait for the report
      showrunner analyze --id <id>             one check: report or exit 2
      showrunner analyze --id <id> --sync      wait until ready
      showrunner analyze --id <id> --transcript --caption

    Artifact flags combine (default: --report) and apply whenever a
    result is available — with --id, or with a PATH under --sync.

    OUTPUT: stdout carries only the payload (the bare post_id for an
    upload; the artifact content for reads), so redirection stays
    clean. Progress/status lines are off by default — --verbose prints
    them on stderr. Warnings and errors always go to stderr.

    UPLOADS are idempotent: the post_id is minted client-side (UUIDv4)
    and transient failures (network errors, 5xx) retry with the same
    id — retrying can never create duplicate drafts. An interrupted
    upload's id is resumed automatically on the next run for the same
    file (via the local ledger).

    Exit codes: 0 = ready/success, 1 = real error or terminally failed
    analysis (failure_reason on stderr), 2 = analysis not ready yet
    (message on stderr; a --sync timeout also exits 2), 3 = duplicate
    refused under --if-duplicate fail.

    Under --json: uploads stream NDJSON events (`upload_progress`,
    optionally `duplicate_warning`, `upload_resume`, `upload_retry`,
    then `submitted` with "deduped": false — or, with --sync,
    `analysis_pending` and a terminal `done` with the artifacts);
    --id prints ONE object {"post_id", "status", + requested
    artifacts}. With --if-duplicate reuse, the `submitted` event
    carries the prior ledger record plus "deduped": true.
    """
    json_mode = _json_mode(ctx, json_output)

    if sum([path is not None, post_id is not None]) != 1:
        raise click.UsageError(
            "Provide exactly one source: a video PATH to upload, or --id ID "
            "for an existing analysis (see `showrunner list`)."
        )

    wants = {
        "report": report, "full": full, "transcript": transcript,
        "overlays": overlays, "scenes": scenes, "caption": caption,
        "video": video_dl, "video_url": video_url,
    }
    any_artifact = (
        any([report, full, transcript, overlays, scenes, caption, video_url])
        or video_dl is not None
    )

    if not any_artifact:
        wants["report"] = True

    if path is not None and not sync:
        if any_artifact:
            raise click.UsageError(
                "Artifact flags need an analysis result: add --sync to wait "
                "for it, or fetch it later with "
                "`showrunner analyze --id <id> ...`."
            )
        if output_path:
            raise click.UsageError(
                "--output requires a result: add --sync, or save it later "
                "with `showrunner analyze --id <id> --output ...`."
            )

    if path is not None:
        code = _submit_analyze(
            Path(path),
            server_url=server_url,
            json_mode=json_mode,
            sync=sync,
            output_path=Path(output_path) if output_path else None,
            timeout=timeout,
            bare_id=True,
            wants=wants,
            if_duplicate=if_duplicate,
            verbose=verbose,
        )
    else:
        code = _fetch_analyze_result(
            post_id,
            server_url=server_url,
            json_mode=json_mode,
            sync=sync,
            timeout=timeout,
            wants=wants,
            output_path=Path(output_path) if output_path else None,
            verbose=verbose,
        )
    if code:
        ctx.exit(code)


@cli.command(name="list")
@click.option("--local", is_flag=True,
              help="Read the local upload ledger "
                   "(~/.showrunner/analyses.jsonl) instead of asking the "
                   "server. Works offline and logged-out.")
@click.option("--limit", type=int, default=20, show_default=True,
              help="Maximum rows. The server caps remote listings at 100 "
                   "(server-side limit only — no pagination cursors yet).")
@click.option("--status", "status_filter",
              type=click.Choice(["pending", "done"]), default=None,
              help="Only rows whose analysis status is known and matches. "
                   "Rows with unknown status never match (local ledger rows "
                   "carry no status).")
@click.option("--server", "server_url", default=None, help="Cloud server URL.")
@_json_flag
@click.pass_context
def list_cmd(ctx, local, limit, status_filter, server_url, json_output):
    """List your uploaded videos (post_id, name, age, analysis status).

    By default asks the server (GET /api/v1/drafts) for the videos your
    account uploaded. NOTE: the remote list currently requires a
    password (Firebase) session — `showrunner login --with-password`;
    OAuth tokens will work once scrollmark/platform#15546 lands.

    --local lists recent uploads recorded in the local ledger instead
    (newest first; works offline). Under --json: the remote list emits
    {"videos": [...raw server records...]}, --local emits
    {"analyses": [...ledger records...]}.
    """
    json_mode = _json_mode(ctx, json_output)

    if local:
        _list_local(json_mode, limit, status_filter)
        return

    _, _, client_mod, credentials = _cloud_import(ctx, json_mode)
    from showrunner.cloud import analyze as analyze_mod  # noqa: PLC0415

    server = _resolve_server(server_url)

    def oauth_hint() -> str | None:
        try:
            creds = credentials.CredentialStore().load(server)
        except Exception:
            return None
        if creds is not None and creds.method != "firebase":
            return (
                "\n\nHint: the remote list currently requires a password "
                "(Firebase) session — OAuth tokens will work once "
                "scrollmark/platform#15546 lands. Re-login with "
                "`showrunner login --with-password` (or use "
                "`showrunner list --local` for the local ledger)."
            )
        return None

    def fail(error: str, message: str) -> None:
        if json_mode:
            click.echo(_json_doc({"error": error, "message": message}))
            ctx.exit(1)
        raise click.ClickException(message)

    try:
        with client_mod.CloudClient(server) as api:
            rows = analyze_mod.list_videos(api, limit=limit)
    except analyze_mod.ListUnauthorized as e:
        message = str(e) + (
            oauth_hint()
            or " Your login may be missing the analysis:read permission — "
               "re-run `showrunner login --with-password`."
        )
        return fail("unauthorized", message)
    except credentials.NotLoggedInError as e:
        return fail("not_logged_in", str(e) + (oauth_hint() or ""))
    except analyze_mod.AnalyzeError as e:
        return fail("list_failed", str(e))
    except Exception as e:  # network and other unexpected failures
        return fail("list_failed", f"unexpected error listing videos: {e}")

    if status_filter:
        rows = [r for r in rows if _derive_status(r) == status_filter]

    if json_mode:
        click.echo(_json_doc({"videos": rows}))
        return
    if not rows:
        click.echo("No uploaded videos found.")
        return
    import time as time_mod  # noqa: PLC0415

    now = time_mod.time()
    for row in rows:
        pid = row.get("post_id") or row.get("id") or "?"
        name = (row.get("filename") or row.get("file_name")
                or row.get("title") or "")
        age = _iso_age(row.get("created_at") or row.get("uploaded_at"), now) or "?"
        status = _derive_status(row) or "-"
        click.echo(f"{pid}  {age:>8}  {status:>8}  {name}".rstrip())


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
        # auth_method: oauth (default — browser PKCE; activates once the
        # server's OAuth chain deploys, scrollmark/showrunner#55) or
        # firebase (email+password — today's working path; same as
        # `showrunner login --with-password`, which overrides this).
        # firebase_api_key overrides the shipped public web API key.
        "cloud": {"server_url": "https://api.gpt.social", "auth_method": "oauth"},
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
