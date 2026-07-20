"""Pipeline orchestrator — drives format through plan -> assets -> compose -> render."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import AsyncIterator, Callable

from showrunner import checkpoints
from showrunner.config import Config, load_config
from showrunner.events import (
    CancelToken,
    CancelledError,
    PipelineCancelled,
    PipelineEvent,
    PipelineFailed,
    PlanReady,
    RenderCompleted,
    StageCompleted,
    StageStarted,
    WorkDirReady,
    emit,
)
from showrunner.formats.registry import get_registry
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style


class Pipeline:
    """Orchestrates video generation through a Format plugin."""

    def __init__(self, format_name: str = "faceless-explainer", config: Config | None = None):
        self.format_name = format_name
        self.config = config or load_config()

    def run(
        self,
        topic: str | None = None,
        *,
        resume_from: Path | None = None,
        style: str | None = None,
        style_override: str | None = None,
        output_path: Path | None = None,
        aspect_ratio: str = "9:16",
        voice: str = "af_heart",
        speed: float = 1.0,
        captions: bool = False,
        watermark: str | None = None,
        parallel: bool = False,
        auto_approve: bool = False,
        no_audio: bool = False,
        dry_run: bool = False,
        preview: bool = False,
        music: str | None = "auto",
        music_volume: float | None = None,
        music_seed: str | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Path | Plan:
        """Run the full pipeline.

        Resumability:
        - Every stage (plan/assets/compose/render) writes a
          `checkpoint_<stage>.json` into the work_dir (see
          `showrunner.checkpoints` and docs/workdir-layout.md).
        - `resume_from=<work_dir>` re-runs the pipeline against an
          existing work_dir, skipping stages whose checkpoint is
          `completed`. The assets stage resumes per-scene (existing
          audio/scene-code/clips are kept). On resume the original run's
          persisted options (voice, aspect ratio, music, ...) are
          replayed from `showrunner.json`; `topic` may be omitted.

        Embeddable hooks for chatbots / web apps:
        - `on_event(ev)` — called at every stage transition with a typed
          `PipelineEvent`. See `showrunner.events` for the schema. Failed
          callbacks are swallowed so user code can't break renders.
        - `cancel_token` — a `CancelToken` checked at scene boundaries
          and stage transitions. `.cancel()` from another thread/task
          unwinds with a `PipelineCancelled` event and a None return.
        """
        registry = get_registry()
        fmt = registry.get(self.format_name)

        resuming = resume_from is not None
        work_dir: Path | None = None
        if resuming:
            work_dir = Path(resume_from)
            if not work_dir.is_dir():
                raise ValueError(f"resume_from work_dir does not exist: {work_dir}")
            meta = self._read_meta(work_dir)
            # Faithful replay: the original run's persisted options win so a
            # resumed render matches what the interrupted run would have made.
            opts = meta.get("options", {})
            aspect_ratio = opts.get("aspect_ratio", meta.get("aspect_ratio", aspect_ratio))
            voice = opts.get("voice", voice)
            speed = opts.get("speed", speed)
            captions = opts.get("captions", captions)
            watermark = opts.get("watermark", watermark)
            parallel = opts.get("parallel", parallel)
            no_audio = opts.get("no_audio", no_audio)
            music = opts.get("music", music)
            music_volume = opts.get("music_volume", music_volume)
            music_seed = opts.get("music_seed", music_seed)
            style = style or meta.get("style")
            topic = topic or meta.get("topic")
        elif topic is None:
            raise ValueError("topic is required unless resume_from is provided")

        style_name = style or self.config.default_style
        resolved_style = resolve_style(style_name, overrides=style_override)

        def _check_cancel() -> bool:
            if cancel_token is not None and cancel_token.is_cancelled:
                emit(on_event, PipelineCancelled())
                return True
            return False

        current_stage = "plan"
        try:
            # Dry-run only needs the LLM — building the full provider set would
            # instantiate render/TTS/video providers (and their API key checks)
            # for no reason, and breaks when the user hasn't configured them.
            if dry_run:
                emit(on_event, StageStarted(stage="plan"))
                llm = self._create_llm(
                    self.config.providers.get("llm", "anthropic"),
                    self.config.provider_config,
                )
                plan_only = fmt.plan(topic, resolved_style, self.config, llm)
                emit(on_event, PlanReady(plan=plan_only))
                emit(on_event, StageCompleted(stage="plan"))
                return plan_only

            # Each format declares its render pipeline via class attrs (see Format base).
            providers = self._create_providers(
                llm_name=self.config.providers.get("llm", "anthropic"),
                tts_name=self.config.providers.get("tts", "kokoro"),
                render_name=fmt.preferred_render_provider,
                provider_config=self.config.provider_config,
                video_name=self.config.providers.get("video") if fmt.requires_video_provider else None,
            )

            # Work dir exists before the plan stage so checkpoints have a home.
            if work_dir is None:
                work_dir = Path(tempfile.mkdtemp(prefix="showrunner-"))
                # Persist run metadata immediately so `showrunner resume` /
                # `showrunner export` can replay this run. The `stages` key
                # is kept in sync by every checkpoint write.
                self._write_meta(
                    work_dir,
                    format_name=fmt.name,
                    aspect_ratio=aspect_ratio,
                    style=style,
                    topic=topic,
                    options={
                        "aspect_ratio": aspect_ratio,
                        "voice": voice,
                        "speed": speed,
                        "captions": captions,
                        "watermark": watermark,
                        "parallel": parallel,
                        "no_audio": no_audio,
                        "music": music,
                        "music_volume": music_volume,
                        "music_seed": music_seed,
                    },
                )

            # Set format options
            fmt._style = resolved_style
            fmt._aspect_ratio = aspect_ratio
            fmt._voice = voice
            fmt._speed = speed
            fmt._parallel = parallel
            fmt._resume = resuming
            fmt._on_event = on_event
            fmt._cancel_token = cancel_token

            # ── Plan ─────────────────────────────────────────────────────
            plan_file = work_dir / "plan.json"
            if resuming and checkpoints.is_stage_completed(work_dir, "plan") and plan_file.exists():
                plan = Plan.from_json(plan_file.read_text(encoding="utf-8"))
                emit(on_event, PlanReady(plan=plan))
            else:
                if topic is None:
                    raise ValueError(
                        "Cannot re-run the plan stage without a topic — the "
                        "work_dir has no completed plan checkpoint and no "
                        "persisted topic in showrunner.json."
                    )
                emit(on_event, StageStarted(stage="plan"))
                checkpoints.mark_stage(work_dir, "plan", checkpoints.STATUS_IN_PROGRESS)
                plan = fmt.plan(topic, resolved_style, self.config, providers["llm"])
                # Persist plan so `showrunner export` / `resume` can rebuild
                # state without re-running the LLM.
                plan_file.write_text(plan.to_json(), encoding="utf-8")
                checkpoints.mark_stage(
                    work_dir, "plan", checkpoints.STATUS_COMPLETED,
                    outputs={"plan_file": "plan.json"},
                )
                emit(on_event, PlanReady(plan=plan))
                emit(on_event, StageCompleted(stage="plan"))
            if _check_cancel():
                return None  # type: ignore[return-value]

            # Music selection needs the plan title as a seed fallback when
            # resuming an old work_dir that didn't persist the topic.
            fmt._music_selection = self._resolve_music(
                music=music, seed=music_seed or topic or plan.title,
                volume=music_volume, preset=resolved_style.preset,
            )

            # Render provider setup is idempotent (template copy + npm
            # install) and required on resume too — a fresh machine won't
            # have node_modules in the work_dir.
            providers["render"].setup(work_dir)
            emit(on_event, WorkDirReady(work_dir=work_dir))

            # ── Assets ───────────────────────────────────────────────────
            current_stage = "assets"
            if resuming and checkpoints.is_stage_completed(work_dir, "assets"):
                cp = checkpoints.read_checkpoint(work_dir, "assets")
                assets = (cp.outputs or {}).get("assets", {}) if cp else {}
            else:
                emit(on_event, StageStarted(stage="assets"))
                checkpoints.mark_stage(work_dir, "assets", checkpoints.STATUS_IN_PROGRESS)
                if not no_audio:
                    assets = fmt.generate_assets(plan, providers, work_dir)
                else:
                    assets = {"has_audio": False, "durations": {}, "width": 1080, "height": 1920}
                checkpoints.mark_stage(
                    work_dir, "assets", checkpoints.STATUS_COMPLETED,
                    outputs={"assets": _jsonable(assets)},
                )
                emit(on_event, StageCompleted(stage="assets"))
            if _check_cancel():
                return None  # type: ignore[return-value]

            # ── Compose ──────────────────────────────────────────────────
            current_stage = "compose"
            if not (resuming and checkpoints.is_stage_completed(work_dir, "compose")):
                emit(on_event, StageStarted(stage="compose"))
                checkpoints.mark_stage(work_dir, "compose", checkpoints.STATUS_IN_PROGRESS)
                fmt.compose(plan, assets, work_dir, captions=captions, watermark=watermark)
                checkpoints.mark_stage(work_dir, "compose", checkpoints.STATUS_COMPLETED)
                emit(on_event, StageCompleted(stage="compose"))

            if preview:
                providers["render"].preview(work_dir)
                return plan

            # ── Render ───────────────────────────────────────────────────
            current_stage = "render"
            if output_path is None:
                output_path = Path.cwd() / "output" / f"{_slugify(plan.title)}.mp4"

            render_cp = checkpoints.read_checkpoint(work_dir, "render")
            if (
                resuming
                and render_cp is not None
                and render_cp.status == checkpoints.STATUS_COMPLETED
                and render_cp.outputs.get("output_path")
                and Path(render_cp.outputs["output_path"]).exists()
            ):
                # Nothing left to do — the finished mp4 is already on disk.
                result = Path(render_cp.outputs["output_path"])
                emit(on_event, RenderCompleted(output_path=result))
                return result

            emit(on_event, StageStarted(stage="render"))
            if _check_cancel():
                return None  # type: ignore[return-value]
            checkpoints.mark_stage(work_dir, "render", checkpoints.STATUS_IN_PROGRESS)
            result = providers["render"].render(work_dir=work_dir, output_path=output_path)
            checkpoints.mark_stage(
                work_dir, "render", checkpoints.STATUS_COMPLETED,
                outputs={"output_path": str(result)},
            )
            emit(on_event, StageCompleted(stage="render"))
            emit(on_event, RenderCompleted(output_path=result))
            return result
        except CancelledError:
            emit(on_event, PipelineCancelled())
            return None  # type: ignore[return-value]
        except Exception as e:
            if work_dir is not None:
                try:
                    cp = checkpoints.read_checkpoint(work_dir, current_stage)
                    if cp is not None and cp.status == checkpoints.STATUS_IN_PROGRESS:
                        checkpoints.mark_stage(
                            work_dir, current_stage, checkpoints.STATUS_FAILED, error=str(e)
                        )
                except Exception:
                    pass  # checkpoint bookkeeping must never mask the real error
            emit(on_event, PipelineFailed(stage=current_stage, error=str(e)))
            raise

    @staticmethod
    def _read_meta(work_dir: Path) -> dict:
        meta_path = Path(work_dir) / "showrunner.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _write_meta(
        work_dir: Path, *, format_name: str, aspect_ratio: str,
        style: str | None, topic: str | None, options: dict,
    ) -> None:
        (Path(work_dir) / "showrunner.json").write_text(
            json.dumps({
                "format": format_name,
                "aspect_ratio": aspect_ratio,
                "style": style,
                "topic": topic,
                "options": options,
                "stages": checkpoints.stages_summary(work_dir),
            }, indent=2),
            encoding="utf-8",
        )

    def refine(
        self,
        work_dir: Path,
        scene_id: str,
        instruction: str,
        *,
        output_path: Path | None = None,
        style: str | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
    ) -> Path:
        """Re-generate a single scene's TSX in an existing work_dir and
        re-render the composition. Reuses existing TTS narration and the
        sibling scenes' code; touches only the named scene.

        Saves ~2 minutes vs. a full pipeline run on a typical 7-scene
        video (no plan, no TTS, no other-scene codegen). Render time is
        unchanged — Remotion always renders the full timeline.

        Returns the path to the new mp4. The work_dir is mutated in
        place (the scene's old TSX is overwritten with the refined one).
        """
        import re as _re
        from showrunner.formats.faceless_explainer.assets import generate_scene_code
        from showrunner.formats.faceless_explainer.composer import generate_root_tsx
        from showrunner.plan import Plan, Scene
        from showrunner.providers.render.remotion import RemotionRenderProvider

        emit(on_event, StageStarted(stage="refine"))

        # Locate the scene file that matches scene_id.
        scenes_dir = work_dir / "src" / "scenes"
        candidate_name = "".join(w.capitalize() for w in scene_id.split("_"))
        scene_path = scenes_dir / f"{candidate_name}.tsx"
        if not scene_path.exists():
            # Fall back to a fuzzy match — handle scene_id's that don't
            # snake-case-roundtrip cleanly (e.g. "step_1_intro").
            matches = [p for p in scenes_dir.glob("*.tsx") if scene_id.lower().replace("_", "") in p.stem.lower().replace("_", "")]
            if not matches:
                raise ValueError(
                    f"scene '{scene_id}' not found in {scenes_dir}. "
                    f"Available: {[p.stem for p in scenes_dir.glob('*.tsx')]}"
                )
            scene_path = matches[0]

        # Read the existing scene + plan to recover narration/duration.
        # Plan reconstruction: parse the existing Root.tsx for sequence
        # offsets to back out scene durations, and the narration WAV
        # filenames for scene ids. Cleaner than re-parsing the storyboard.
        root_tsx = (work_dir / "src" / "Root.tsx").read_text(encoding="utf-8")
        scene_components = _re.findall(r'import\s+(\w+)\s+from\s+"./scenes/(\w+)"', root_tsx)
        # Audio sequence durations let us recover scene durations.
        audio_durations: dict[str, int] = {}
        for m in _re.finditer(
            r'<Sequence\s+from=\{(\d+)\}\s+durationInFrames=\{(\d+)\}>\s*\n\s*<Audio\s+src=\{staticFile\("audio/([^"]+)\.wav"\)',
            root_tsx,
        ):
            audio_durations[m.group(3)] = int(m.group(2))

        fps = 30  # composer hardcodes this; matches preset.rhythm.fps
        target_scene_id = scene_path.stem  # e.g. "HookProblem" → match by component name
        # We want the original scene_id (snake_case). Find it by mapping
        # component name back to the matching audio file.
        original_scene_id = next(
            (sid for sid in audio_durations if "".join(w.capitalize() for w in sid.split("_")) == target_scene_id),
            scene_id,
        )

        duration_frames = audio_durations.get(original_scene_id, 5 * fps)
        scene = Scene(
            id=original_scene_id,
            duration=max(int(round(duration_frames / fps)), 1),
            narration="(reusing existing TTS narration)",
            visual=instruction,  # the new instruction becomes the visual brief
            transition=None,
        )

        # Resolve the active style — caller may override; otherwise use
        # the configured default. The preset is needed for the codegen
        # prompt to inject style_context.
        style_name = style or self.config.default_style
        resolved_style = resolve_style(style_name)
        emit(on_event, StageStarted(stage="refine_scene_codegen"))

        llm = self._create_llm(
            self.config.providers.get("llm", "anthropic"),
            self.config.provider_config,
        )
        render = RemotionRenderProvider()

        # validate_fn writes the candidate to disk + tsc-checks it.
        def validate_fn(sid: str, code: str) -> tuple[bool, str]:
            scene_path.write_text(code, encoding="utf-8")
            return render.validate_scene(work_dir, sid)

        # Refinement prompt: append the user's instruction to the visual
        # brief so the codegen system has both the original intent and
        # the change request.
        refined_visual = (
            f"REFINEMENT (revise the existing scene): {instruction}\n\n"
            "Keep the scene's structure and timing similar; change only what "
            "the refinement asks for. Match the established visual style of "
            "sibling scenes."
        )
        scene = Scene(
            id=original_scene_id,
            duration=scene.duration,
            narration=scene.narration,
            visual=refined_visual,
            transition=None,
        )
        new_code = generate_scene_code(
            scene=scene,
            style_context=resolved_style.to_prompt_context(),
            llm=llm,
            validate_fn=validate_fn,
            width=1920 if "16" in (work_dir / "src" / "Root.tsx").read_text()[:500] else 1080,
            height=1080,
            fps=fps,
        )
        scene_path.write_text(new_code, encoding="utf-8")
        emit(on_event, StageCompleted(stage="refine_scene_codegen"))

        # Re-run only the Remotion render; compose stays as-is (Root.tsx
        # already references the scene by its component name, so the new
        # TSX is picked up automatically).
        emit(on_event, StageStarted(stage="render"))
        if output_path is None:
            output_path = work_dir / "refined.mp4"
        result = render.render(work_dir=work_dir, output_path=output_path)
        emit(on_event, StageCompleted(stage="render"))
        emit(on_event, RenderCompleted(output_path=result))
        emit(on_event, StageCompleted(stage="refine"))
        return result

    async def arun(
        self,
        topic: str,
        **kwargs,
    ) -> AsyncIterator[PipelineEvent]:
        """Async event-stream wrapper around `run()`. Yields each event
        as it happens; the final event is `RenderCompleted` (or
        `PipelineFailed` / `PipelineCancelled`).

        Usage:

            async for event in pipeline.arun(topic="..."):
                if isinstance(event, RenderCompleted):
                    print(f"done: {event.output_path}")
                else:
                    update_ui(event)
        """
        import asyncio
        import threading

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        DONE = object()

        def callback(ev: PipelineEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, ev)

        def runner() -> None:
            try:
                self.run(topic, on_event=callback, **kwargs)
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait, PipelineFailed(stage="unknown", error=str(e))
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, DONE)

        threading.Thread(target=runner, daemon=True).start()

        while True:
            ev = await queue.get()
            if ev is DONE:
                break
            yield ev

    def _resolve_music(self, *, music: str | None, seed: str, volume: float | None, preset: dict):
        """Turn the CLI's `--music` into a concrete track (or None).

        Values: "none" / None → no music. "auto" → mood-picked from the
        preset. Anything else → track id lookup.
        """
        from showrunner.music import MusicCatalog, MusicPicker

        if music in (None, "none"):
            return None
        catalog = MusicCatalog.load()
        if not catalog.tracks:
            # Graceful no-op when the user hasn't provisioned a catalog yet.
            return None

        if music == "auto":
            track = MusicPicker(catalog).pick_for_preset(preset, seed=seed)
        else:
            track = catalog.get(music)
            if track is None:
                raise ValueError(
                    f"Music track '{music}' not in catalog. "
                    "Run `showrunner music list` to see available tracks."
                )
        if track is None:
            return None
        preset_volume = (preset.get("music") or {}).get("volume", 0.2)
        return {
            "track": track,
            "audio_path": catalog.resolve_audio_path(track),
            "volume": volume if volume is not None else preset_volume,
        }

    def _create_llm(self, llm_name: str, provider_config: dict):
        if llm_name == "anthropic":
            from showrunner.providers.llm.anthropic import AnthropicLLMProvider

            cfg = provider_config.get("anthropic", {})
            return AnthropicLLMProvider(model=cfg.get("model", "claude-sonnet-4-5-20250929"))
        if llm_name == "openai":
            from showrunner.providers.llm.openai import OpenAILLMProvider

            cfg = provider_config.get("openai", {})
            return OpenAILLMProvider(model=cfg.get("model", "gpt-4o"))
        raise ValueError(f"Unknown LLM provider: {llm_name}")

    def _create_providers(
        self, llm_name: str, tts_name: str, render_name: str, provider_config: dict,
        video_name: str | None = None,
    ) -> dict:
        providers = {"llm": self._create_llm(llm_name, provider_config)}

        if tts_name == "kokoro":
            from showrunner.providers.tts.kokoro import KokoroTTSProvider

            providers["tts"] = KokoroTTSProvider()
        elif tts_name == "elevenlabs":
            from showrunner.providers.tts.elevenlabs import ElevenLabsTTSProvider

            cfg = provider_config.get("elevenlabs", {})
            providers["tts"] = ElevenLabsTTSProvider(api_key=cfg.get("api_key"))
        else:
            raise ValueError(f"Unknown TTS provider: {tts_name}")

        if render_name == "remotion":
            from showrunner.providers.render.remotion import RemotionRenderProvider

            providers["render"] = RemotionRenderProvider()
        elif render_name == "ffmpeg":
            from showrunner.providers.render.ffmpeg import FFmpegRenderProvider

            providers["render"] = FFmpegRenderProvider()
        else:
            raise ValueError(f"Unknown render provider: {render_name}")

        if video_name:
            if video_name == "minimax":
                from showrunner.providers.video.minimax import MinimaxVideoProvider

                cfg = provider_config.get("minimax", {})
                providers["video"] = MinimaxVideoProvider(
                    api_key=cfg.get("api_key"), model=cfg.get("model", "video-01-live2d")
                )
            elif video_name == "gemini":
                from showrunner.providers.video.gemini import GeminiVideoProvider

                cfg = provider_config.get("gemini", {})
                providers["video"] = GeminiVideoProvider(
                    api_key=cfg.get("api_key"), model=cfg.get("model", "veo-3.1-generate-preview")
                )
            else:
                raise ValueError(f"Unknown video provider: {video_name}")

        return providers


def _jsonable(value):
    """Recursively convert asset metadata to JSON-serializable types
    (Paths become strings) so it can live inside a checkpoint file."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]
