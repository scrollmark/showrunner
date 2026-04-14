"""Compose Root.tsx timeline from plan + scenes."""

from __future__ import annotations

from showrunner.plan import Plan


# Map planner-emitted transition names to @remotion/transitions presentations.
# Keep this narrow — the presets choose from the same menu.
_TRANSITION_PRESENTATIONS: dict[str, str] = {
    "fade":        'fade()',
    "slide-left":  'slide({ direction: "from-right" })',
    "slide-right": 'slide({ direction: "from-left" })',
    "slide-up":    'slide({ direction: "from-bottom" })',
    "slide-down":  'slide({ direction: "from-top" })',
    "wipe":        'wipe({ direction: "from-right" })',
    "flip":        'flip({ direction: "from-right" })',
    "zoom-in":     'fade()',  # @remotion/transitions has no zoom; fade is the closest out-of-box.
}


def _presentation_for(transition: str | None) -> str:
    return _TRANSITION_PRESENTATIONS.get(transition or "fade", "fade()")


def _resolve_transition_frames(preset: dict | None, fps: int) -> int:
    """Number of frames each scene-to-scene transition occupies.

    Mirrors the TS-side `transitionFrames()` helper in tokens/rhythm.ts so
    the Python-computed `durationInFrames` matches the runtime overlap.
    """
    if not preset:
        return max(int(fps * 0.33), 1)  # ~10 frames at 30fps, legacy default
    rhythm = preset.get("rhythm") or {}
    bpm = rhythm.get("bpm", 120)
    beats = rhythm.get("transitionBeats", 1.0)
    beat_frames = (60 / bpm) * fps
    return max(int(round(beats * beat_frames)), 1)


def generate_root_tsx(
    plan: Plan,
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    has_audio: bool = True,
    captions: bool = False,
    watermark: str | None = None,
    preset: dict | None = None,
    music: dict | None = None,
) -> str:
    """Generate Root.tsx content for a Remotion composition.

    Uses @remotion/transitions.TransitionSeries so cuts carry real easing
    and crossfades; transition duration is derived from the active preset's
    `rhythm.transitionBeats` via the tokens module (`transitionFrames()`).

    If `preset` is provided, the visual timeline's total duration accounts
    for TransitionSeries's scene overlap so the composition doesn't render
    a black-frame tail. Without the preset we fall back to the naive sum
    (this only matters for unit tests that don't care about exact frame
    counts).
    """
    scenes = plan.scenes
    transition_frames = _resolve_transition_frames(preset, fps)

    components = []
    for scene in scenes:
        name = "".join(w.capitalize() for w in scene.id.split("_"))
        components.append({"name": name, "scene": scene})

    # TransitionSeries overlaps consecutive scenes by `transition_frames`,
    # so scene k's visual timeline starts at sum(d0..d_{k-1}) - k×t, not
    # the naive sum(d0..d_{k-1}). The audio sequences run on the SAME
    # compressed timeline so narration stays in sync with visuals and
    # doesn't trail past the last scene's visual end.
    audio_offsets = []
    compressed = 0  # cumulative frame offset in the transition-compressed timeline
    for i, comp in enumerate(components):
        duration_frames = comp["scene"].duration * fps
        audio_offsets.append({
            "name": comp["name"],
            "scene": comp["scene"],
            "from_frame": compressed,
            "duration_frames": duration_frames,
        })
        # After scene i, advance by d_i - t (the transition overlaps the
        # tail of this scene with the head of the next). Don't subtract
        # transition after the final scene.
        compressed += duration_frames - (transition_frames if i < len(components) - 1 else 0)
    visual_series_end = compressed
    outro_frames = int(music.get("extra_frames", 0)) if music else 0
    visual_total_frames = visual_series_end + outro_frames
    # Preserve the naive sum so callers who reason about total scene
    # duration still have that value.
    total_frames_naive = sum(c["scene"].duration * fps for c in components)

    lines = [
        'import React from "react";',
        'import { AbsoluteFill, Composition, Sequence, Audio, staticFile, useCurrentFrame, useVideoConfig } from "remotion";',
        'import { TransitionSeries, linearTiming } from "@remotion/transitions";',
        'import { fade } from "@remotion/transitions/fade";',
        'import { slide } from "@remotion/transitions/slide";',
        'import { wipe } from "@remotion/transitions/wipe";',
        'import { flip } from "@remotion/transitions/flip";',
        'import { curve, motion, transitionFrames } from "./tokens";',
    ]
    if music and music.get("has_envelope"):
        lines.append('import { envelope, BASE_VOLUME } from "./music/envelope.generated";')
    for comp in components:
        lines.append(f'import {comp["name"]} from "./scenes/{comp["name"]}";')

    lines.append("")
    if captions:
        lines.append(_caption_overlay_code(components))
        lines.append("")

    # MyComposition
    lines.append("export const MyComposition: React.FC = () => {")
    lines.append("  const tFrames = transitionFrames();")
    lines.append("  const tEasing = curve(motion.transitionCurve);")
    lines.append("  return (")
    lines.append("    <AbsoluteFill>")
    lines.append("      <TransitionSeries>")

    for i, comp in enumerate(components):
        duration_frames = comp["scene"].duration * fps
        lines.append(f'        <TransitionSeries.Sequence durationInFrames={{{duration_frames}}}>')
        lines.append(f'          <{comp["name"]} />')
        lines.append(f'        </TransitionSeries.Sequence>')
        if i < len(components) - 1:
            next_scene = components[i + 1]["scene"]
            presentation = _presentation_for(getattr(next_scene, "transition", None))
            lines.append(f'        <TransitionSeries.Transition')
            lines.append(f'          presentation={{{presentation}}}')
            lines.append('          timing={linearTiming({ durationInFrames: tFrames, easing: tEasing })}')
            lines.append(f'        />')

    lines.append('      </TransitionSeries>')

    if has_audio:
        for ao in audio_offsets:
            lines.append(f'      <Sequence from={{{ao["from_frame"]}}} durationInFrames={{{ao["duration_frames"]}}}>')
            lines.append(f'        <Audio src={{staticFile("audio/{ao["scene"].id}.wav")}} />')
            lines.append('      </Sequence>')

    # Background music bed. If the compose step produced a per-frame
    # ducking envelope, we import and sample it; otherwise the volume is
    # a flat constant.
    if music and music.get("filename"):
        volume = float(music.get("volume", 0.2))
        filename = music["filename"]
        if music.get("has_envelope"):
            lines.append(
                f'      <Audio src={{staticFile("music/{filename}")}} '
                f'volume={{(f: number) => envelope[f] ?? BASE_VOLUME}} />'
            )
        else:
            lines.append(
                f'      <Audio src={{staticFile("music/{filename}")}} volume={{{volume}}} />'
            )

    if captions:
        lines.append("      <CaptionOverlay />")

    if watermark:
        lines.append(
            '      <div style={{ position: "absolute", top: 40, right: 40, '
            'color: "rgba(255,255,255,0.4)", fontSize: 24, fontFamily: "Inter" }}>'
        )
        lines.append(f'        {watermark}')
        lines.append('      </div>')

    lines.append("    </AbsoluteFill>")
    lines.append("  );")
    lines.append("};")
    lines.append("")

    # RemotionRoot
    lines.append("export const RemotionRoot: React.FC = () => {")
    lines.append("  return (")
    lines.append("    <Composition")
    lines.append('      id="main"')
    lines.append("      component={MyComposition}")
    lines.append(f"      durationInFrames={{{visual_total_frames}}}")
    lines.append(f"      fps={{{fps}}}")
    lines.append(f"      width={{{width}}}")
    lines.append(f"      height={{{height}}}")
    lines.append("    />")
    lines.append("  );")
    lines.append("};")
    lines.append("")

    return "\n".join(lines)


def _caption_overlay_code(components: list[dict]) -> str:
    return '''const CaptionOverlay: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Caption overlay — word-by-word reveal synced with narration
  // (Phase 3 will wire TTS word boundaries through the planner and
  // render per-word spans here.)
  return (
    <div style={{
      position: "absolute",
      bottom: 120,
      left: 60,
      right: 60,
      textAlign: "center",
      fontSize: 36,
      fontFamily: "Inter",
      color: "white",
      textShadow: "0 2px 8px rgba(0,0,0,0.8)",
      fontWeight: 600,
    }}>
      {/* Captions rendered per-scene based on frame position */}
    </div>
  );
};'''
