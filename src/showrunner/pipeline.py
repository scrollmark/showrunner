"""Pipeline orchestrator — drives format through plan -> assets -> compose -> render."""

from __future__ import annotations

import json
import re
import tempfile
import threading
from pathlib import Path
from typing import AsyncIterator, Callable

from showrunner import checkpoints
from showrunner.config import Config, load_config
from showrunner.costs import (
    CostEstimate,
    collect_usage,
    estimate_pipeline_cost,
    usage_cost_usd,
)
from showrunner.events import (
    STAGE_PROGRESS,
    CancelToken,
    CancelledError,
    PipelineCancelled,
    PipelineCancelledError,
    PipelineEvent,
    PipelineFailed,
    PlanReady,
    RenderCompleted,
    RepairAttempt,
    StageCompleted,
    StageStarted,
    WorkDirReady,
    emit,
)
from showrunner.feedback import Feedback
from showrunner.formats.registry import get_registry
from showrunner.plan import Plan
from showrunner.styles.resolver import resolve_style

#: Name of the run manifest written into every work_dir. Holds the plan,
#: run status, and (after the run) actual usage + cost — the file a host
#: reads to resume a cancelled run or reconcile spend.
MANIFEST_NAME = "showrunner.json"

#: How many trailing lines of render error output to keep when feeding
#: it back to the LLM — Remotion stack traces are huge.
ERROR_TAIL_LINES = 80


def _stage_started(stage: str) -> StageStarted:
    span = STAGE_PROGRESS.get(stage)
    return StageStarted(stage=stage, progress_pct=span[0] if span else None)


def _stage_completed(stage: str) -> StageCompleted:
    span = STAGE_PROGRESS.get(stage)
    return StageCompleted(stage=stage, progress_pct=span[1] if span else None)


class _MergedCancelToken(CancelToken):
    """Cancels when ANY of its sources cancel — used when a caller
    passes both `cancel_token` and `cancel_event`."""

    def __init__(self, sources: list[CancelToken]):
        super().__init__()
        self._sources = sources

    def cancel(self) -> None:
        for source in self._sources:
            source.cancel()

    @property
    def is_cancelled(self) -> bool:
        return any(source.is_cancelled for source in self._sources)


class Pipeline:
    """Orchestrates video generation through a Format plugin."""

    def __init__(self, format_name: str = "faceless-explainer", config: Config | None = None):
        self.format_name = format_name
        self.config = config or load_config()

    def run(
        self,
        topic: str | None = None,
        *,
        plan: Plan | None = None,
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
        cancel_event: threading.Event | None = None,
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
        - `plan=<Plan>` supplies a hand-authored storyboard and skips the
          LLM planner entirely (the CLI's `--storyboard`); the plan is
          still persisted and checkpointed like a normal completed plan
          stage, so downstream stages and `showrunner resume` see no
          difference. `topic` is optional in this case (used only as a
          label/music-seed fallback) but at least one of `topic` or
          `plan` is required.

        Embeddable hooks for chatbots / web apps (see docs/embedding.md):
        - `on_event(ev)` — called at every stage transition with a typed
          `PipelineEvent`. See `showrunner.events` for the schema and
          stability contract. Failed callbacks are swallowed so user
          code can't break renders.
        - `cancel_token` / `cancel_event` — cooperative cancellation,
          checked between scenes and stages. Trip either (a
          `CancelToken.cancel()` or a plain `threading.Event.set()`)
          from another thread/task and the pipeline emits a
          `PipelineCancelled` event, leaves the work_dir resumable on
          disk (with its `showrunner.json` manifest), and raises
          `PipelineCancelledError`.
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
        elif topic is None and plan is None:
            raise ValueError("topic is required unless resume_from or plan is provided")

        style_name = style or self.config.default_style
        resolved_style = resolve_style(style_name, overrides=style_override)

        llm_name = self.config.providers.get("llm", "anthropic")
        tts_name = self.config.providers.get("tts", "kokoro")
        video_name = self.config.providers.get("video") if fmt.requires_video_provider else None

        # Normalize the two cancellation inputs into a single token.
        if cancel_event is not None:
            event_token = CancelToken(event=cancel_event)
            cancel_token = (
                event_token if cancel_token is None
                else _MergedCancelToken([cancel_token, event_token])
            )

        def _checkpoint() -> None:
            if cancel_token is not None:
                cancel_token.raise_if_cancelled()

        providers: dict | None = None
        current_stage = "plan"
        try:
            _checkpoint()
            emit(on_event, _stage_started("plan"))
            # Dry-run only needs the LLM — building the full provider set would
            # instantiate render/TTS/video providers (and their API key checks)
            # for no reason, and breaks when the user hasn't configured them.
            if dry_run:
                if plan is not None:
                    emit(on_event, PlanReady(plan=plan))
                    emit(on_event, _stage_completed("plan"))
                    return plan
                llm = self._create_llm(llm_name, self.config.provider_config)
                plan_only = fmt.plan(topic, resolved_style, self.config, llm)
                emit(on_event, PlanReady(plan=plan_only))
                emit(on_event, _stage_completed("plan"))
                return plan_only

            # Each format declares its render pipeline via class attrs (see Format base).
            providers = self._create_providers(
                llm_name=llm_name,
                tts_name=tts_name,
                render_name=fmt.preferred_render_provider,
                provider_config=self.config.provider_config,
                video_name=video_name,
            )

            # Work dir exists before the plan stage so checkpoints have a home.
            if work_dir is None:
                work_dir = Path(tempfile.mkdtemp(prefix="showrunner-"))
                # Persist run metadata immediately so `showrunner resume` /
                # `showrunner export` can replay this run. The `stages` key
                # is kept in sync by every checkpoint write.
                self._write_manifest(
                    work_dir,
                    format=self.format_name,
                    aspect_ratio=aspect_ratio,
                    style=style,
                    topic=topic,
                    stages=checkpoints.stages_summary(work_dir),
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
            # Formats need the captions flag during asset generation (word
            # timing extraction happens right after TTS), not only at
            # compose time.
            fmt._captions = captions
            fmt._on_event = on_event
            fmt._cancel_token = cancel_token
            # Video-clip formats (ai-video) still need generate_assets() to
            # run clip generation when no_audio is set — only the narration
            # step is skippable. Formats with no external video provider
            # (faceless-explainer, manim) have nothing to generate without
            # audio, so they keep the cheap stub below.
            fmt._no_audio = no_audio

            # ── Plan ─────────────────────────────────────────────────────
            plan_file = work_dir / "plan.json"
            if resuming and checkpoints.is_stage_completed(work_dir, "plan") and plan_file.exists():
                plan = Plan.from_json(plan_file.read_text(encoding="utf-8"))
                emit(on_event, PlanReady(plan=plan))
                emit(on_event, _stage_completed("plan"))
            elif plan is not None:
                # Caller supplied a hand-authored plan (CLI --storyboard) —
                # skip the LLM planner but persist + checkpoint identically
                # to an LLM-generated plan so downstream stages and
                # `showrunner resume` see a normal completed plan stage.
                checkpoints.mark_stage(work_dir, "plan", checkpoints.STATUS_IN_PROGRESS)
                plan_file.write_text(plan.to_json(), encoding="utf-8")
                checkpoints.mark_stage(
                    work_dir, "plan", checkpoints.STATUS_COMPLETED,
                    outputs={"plan_file": "plan.json"},
                )
                emit(on_event, PlanReady(plan=plan))
                emit(on_event, _stage_completed("plan"))
            else:
                if topic is None:
                    raise ValueError(
                        "Cannot re-run the plan stage without a topic — the "
                        "work_dir has no completed plan checkpoint and no "
                        "persisted topic in showrunner.json."
                    )
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
                emit(on_event, _stage_completed("plan"))
            _checkpoint()

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
            # Persist the plan immediately so a cancelled/crashed run
            # leaves a resumable work_dir behind.
            self._write_manifest(
                work_dir,
                status="in_progress",
                topic=topic,
                format=self.format_name,
                style=style_name,
                title=plan.title,
                plan=plan.to_dict(),
            )
            emit(on_event, WorkDirReady(work_dir=work_dir))

            # ── Assets ───────────────────────────────────────────────────
            current_stage = "assets"

            def _generate_assets(current_plan: Plan) -> dict:
                if not no_audio or fmt.requires_video_provider:
                    return fmt.generate_assets(current_plan, providers, work_dir)
                return {"has_audio": False, "durations": {}, "width": 1080, "height": 1920}

            if resuming and checkpoints.is_stage_completed(work_dir, "assets"):
                cp = checkpoints.read_checkpoint(work_dir, "assets")
                assets = (cp.outputs or {}).get("assets", {}) if cp else {}
            else:
                emit(on_event, _stage_started("assets"))
                checkpoints.mark_stage(work_dir, "assets", checkpoints.STATUS_IN_PROGRESS)
                assets = _generate_assets(plan)
                checkpoints.mark_stage(
                    work_dir, "assets", checkpoints.STATUS_COMPLETED,
                    outputs={"assets": _jsonable(assets)},
                )
                emit(on_event, _stage_completed("assets"))
            _checkpoint()

            # ── Compose ──────────────────────────────────────────────────
            current_stage = "compose"
            if not (resuming and checkpoints.is_stage_completed(work_dir, "compose")):
                emit(on_event, _stage_started("compose"))
                checkpoints.mark_stage(work_dir, "compose", checkpoints.STATUS_IN_PROGRESS)
                fmt.compose(plan, assets, work_dir, captions=captions, watermark=watermark)
                checkpoints.mark_stage(work_dir, "compose", checkpoints.STATUS_COMPLETED)
                emit(on_event, _stage_completed("compose"))
            _checkpoint()

            if preview:
                providers["render"].preview(work_dir)
                return plan

            # ── Render ───────────────────────────────────────────────────
            # Runs with a bounded error-repair loop. On failure, the
            # error output is truncated and fed back through
            # `Format.revise()` as asset-level Feedback, the assets are
            # regenerated and recomposed, and the render is retried, up
            # to `config.repair_attempts` times (default 2).
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

            emit(on_event, _stage_started("render"))
            _checkpoint()
            checkpoints.mark_stage(work_dir, "render", checkpoints.STATUS_IN_PROGRESS)
            repair_attempts = max(int(getattr(self.config, "repair_attempts", 2)), 0)
            first_error: str | None = None
            attempt = 0
            while True:
                try:
                    result = providers["render"].render(
                        work_dir=work_dir, output_path=output_path
                    )
                    break
                except CancelledError:
                    raise
                except Exception as render_error:
                    error_text = _truncate_error(str(render_error))
                    if first_error is None:
                        first_error = error_text
                    if attempt >= repair_attempts:
                        raise RuntimeError(
                            f"Render failed after {attempt + 1} attempt(s) "
                            f"({attempt} repair attempt(s), repair_attempts={repair_attempts}).\n"
                            f"--- first error ---\n{first_error}\n"
                            f"--- final error ---\n{error_text}"
                        ) from render_error
                    attempt += 1
                    scene_id = _find_failing_scene(plan, error_text)
                    emit(on_event, RepairAttempt(
                        attempt=attempt, max_attempts=repair_attempts,
                        error=error_text, scene_id=scene_id,
                    ))
                    feedback = Feedback(
                        level="asset",
                        scene_id=scene_id,
                        text=(
                            "The video render failed with the error output below. "
                            "Revise the storyboard so the failing scene(s) render "
                            "successfully; keep everything unrelated to the error "
                            "unchanged.\n\n" + error_text
                        ),
                    )
                    plan = fmt.revise(plan, feedback, providers["llm"])
                    # Keep the persisted plan + checkpoints truthful: the
                    # repair loop re-runs assets and compose on the revised
                    # plan before retrying the render.
                    plan_file.write_text(plan.to_json(), encoding="utf-8")
                    _checkpoint()
                    checkpoints.mark_stage(work_dir, "assets", checkpoints.STATUS_IN_PROGRESS)
                    assets = _generate_assets(plan)
                    checkpoints.mark_stage(
                        work_dir, "assets", checkpoints.STATUS_COMPLETED,
                        outputs={"assets": _jsonable(assets)},
                    )
                    fmt.compose(plan, assets, work_dir, captions=captions, watermark=watermark)
                    checkpoints.mark_stage(work_dir, "compose", checkpoints.STATUS_COMPLETED)
                    checkpoints.mark_stage(work_dir, "render", checkpoints.STATUS_IN_PROGRESS)
                    _checkpoint()
            checkpoints.mark_stage(
                work_dir, "render", checkpoints.STATUS_COMPLETED,
                outputs={"output_path": str(result)},
            )
            emit(on_event, _stage_completed("render"))

            # Reconcile: aggregate actual provider usage + price it.
            usage = collect_usage(providers)
            cost = usage_cost_usd(
                usage, llm_name=llm_name, tts_name=tts_name,
                video_name=video_name, providers=providers,
            ) if usage else None
            self._write_manifest(
                work_dir,
                status="completed",
                output_path=str(result),
                usage=usage,
                cost_usd=cost,
                # Re-persist the plan: a repair loop may have revised it.
                plan=plan.to_dict(),
            )
            emit(on_event, RenderCompleted(output_path=result, usage=usage or None, cost_usd=cost))
            return result
        except CancelledError:
            # Leave the work_dir resumable: record what we know so far.
            usage = collect_usage(providers) if providers else {}
            if work_dir is not None:
                self._write_manifest(work_dir, status="cancelled", usage=usage)
            emit(on_event, PipelineCancelled(work_dir=work_dir))
            raise PipelineCancelledError(work_dir=work_dir) from None
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
                self._write_manifest(work_dir, status="failed", error=str(e))
            emit(on_event, PipelineFailed(stage=current_stage, error=str(e)))
            raise

    @staticmethod
    def _read_meta(work_dir: Path) -> dict:
        meta_path = Path(work_dir) / MANIFEST_NAME
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def estimate(
        self,
        topic: str = "",
        *,
        num_scenes: int = 6,
        avg_scene_seconds: float = 6.0,
        providers: dict | None = None,
    ) -> CostEstimate:
        """Estimate the cost of a run BEFORE running it (no API calls,
        no provider instantiation).

        Per-stage figures cover LLM tokens (plan + per-scene codegen),
        TTS characters, video-generation seconds (the dominant cost for
        ai-video), and local render compute time. Prices come from
        static tables in `showrunner.costs`, unless live provider
        instances with `estimate_cost()` hooks are passed via
        `providers`. `topic` is accepted for signature parity with
        `run()`; it doesn't currently influence the estimate.

        Hosts following an estimate -> reserve -> reconcile lifecycle
        reserve `estimate(...).total_usd`, then reconcile against the
        `usage`/`cost_usd` on the `RenderCompleted` event (also written
        to the work_dir's `showrunner.json`).
        """
        registry = get_registry()
        fmt = registry.get(self.format_name)
        video_name = None
        if fmt.requires_video_provider:
            video_name = self.config.providers.get("video") or "gemini"
        return estimate_pipeline_cost(
            format_name=self.format_name,
            llm_name=self.config.providers.get("llm", "anthropic"),
            tts_name=self.config.providers.get("tts", "kokoro"),
            render_name=fmt.preferred_render_provider,
            video_name=video_name,
            scene_codegen=not fmt.requires_video_provider,
            num_scenes=num_scenes,
            avg_scene_seconds=avg_scene_seconds,
            providers=providers,
        )

    @staticmethod
    def _write_manifest(work_dir: Path, **fields) -> None:
        """Merge fields into `work_dir/showrunner.json`. Best-effort:
        manifest problems must never break a render."""
        path = work_dir / MANIFEST_NAME
        data: dict = {}
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        data.update({k: v for k, v in fields.items() if v is not None})
        try:
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

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
            except PipelineCancelledError:
                pass  # PipelineCancelled event already delivered via callback
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
        from showrunner.providers.registry import create_provider

        return create_provider("llm", llm_name, provider_config)

    def _create_providers(
        self, llm_name: str, tts_name: str, render_name: str, provider_config: dict,
        video_name: str | None = None,
    ) -> dict:
        # Providers resolve via entry points (showrunner.providers.<kind>);
        # see providers/registry.py. Only the selected providers are imported.
        from showrunner.providers.registry import create_provider

        providers = {
            "llm": self._create_llm(llm_name, provider_config),
            "tts": create_provider("tts", tts_name, provider_config),
            "render": create_provider("render", render_name, provider_config),
        }
        if video_name:
            providers["video"] = create_provider("video", video_name, provider_config)
        return providers


def _jsonable(value):
    """Recursively convert asset metadata to JSON-serializable types
    (Paths become strings) so it can live inside a checkpoint file.
    Unknown types are stringified — checkpoint bookkeeping must never
    crash a render over an exotic asset value."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_]+", "-", slug).strip("-")[:80]


def _truncate_error(text: str, max_lines: int = ERROR_TAIL_LINES) -> str:
    """Keep only the last `max_lines` lines of an error blob — render
    stack traces (Remotion especially) run to hundreds of lines, and the
    actionable part is at the end."""
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    omitted = len(lines) - max_lines
    return f"[... {omitted} earlier line(s) truncated ...]\n" + "\n".join(lines[-max_lines:])


def _find_failing_scene(plan: Plan, error_text: str) -> str | None:
    """Best-effort: identify which scene an error blob points at, by
    looking for the scene id (snake_case, as in audio/clip filenames)
    or its CamelCase component name (as in Remotion TSX paths). Returns
    None when no single scene is identifiable."""
    for scene in plan.scenes:
        camel = "".join(w.capitalize() for w in scene.id.split("_"))
        for needle in (scene.id, camel):
            if needle and re.search(rf"\b{re.escape(needle)}\b", error_text):
                return scene.id
    return None
