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


def generate_root_tsx(
    plan: Plan,
    *,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    has_audio: bool = True,
    captions: bool = False,
    watermark: str | None = None,
) -> str:
    """Generate Root.tsx content for a Remotion composition.

    Uses @remotion/transitions.TransitionSeries so cuts carry real easing
    and crossfades; transition duration is derived from the active preset's
    `rhythm.transitionBeats` via the tokens module (`transitionFrames()`).
    """
    scenes = plan.scenes

    components = []
    for scene in scenes:
        name = "".join(w.capitalize() for w in scene.id.split("_"))
        components.append({"name": name, "scene": scene})

    # Per-scene absolute frame offsets for AUDIO sequences only. These use
    # the raw scene durations without transition-overlap — audio is its
    # own layer and the music bed is independent of the visual cross-fade.
    audio_offsets = []
    current = 0
    for comp in components:
        duration_frames = comp["scene"].duration * fps
        audio_offsets.append({
            "name": comp["name"],
            "scene": comp["scene"],
            "from_frame": current,
            "duration_frames": duration_frames,
        })
        current += duration_frames
    total_frames_naive = current

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
    lines.append(f"      durationInFrames={{{total_frames_naive}}}")
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
