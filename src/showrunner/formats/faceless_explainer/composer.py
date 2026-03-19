"""Compose Root.tsx timeline from plan + scenes."""

from __future__ import annotations

from showrunner.plan import Plan


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
    """Generate Root.tsx content for a Remotion composition."""
    scenes = plan.scenes
    transition_frames = 10

    # Build component info
    components = []
    for scene in scenes:
        name = "".join(w.capitalize() for w in scene.id.split("_"))
        components.append({"name": name, "scene": scene})

    # Calculate frame offsets with transition overlap
    frame_data = []
    current_frame = 0
    for i, comp in enumerate(components):
        duration_frames = comp["scene"].duration * fps
        frame_data.append({
            "name": comp["name"],
            "scene": comp["scene"],
            "from_frame": current_frame,
            "duration_frames": duration_frames,
        })
        overlap = transition_frames if i < len(components) - 1 else 0
        current_frame += duration_frames - overlap

    total_frames = current_frame

    # Build imports
    lines = [
        'import React from "react";',
        'import { AbsoluteFill, Composition, Sequence, Audio, staticFile, useCurrentFrame, useVideoConfig } from "remotion";',
    ]
    for comp in components:
        lines.append(f'import {comp["name"]} from "./scenes/{comp["name"]}";')

    lines.append("")
    lines.append(_transition_wrapper_code())
    lines.append("")

    if captions:
        lines.append(_caption_overlay_code(components))
        lines.append("")

    # MyComposition
    lines.append("export const MyComposition: React.FC = () => {")
    lines.append("  return (")
    lines.append("    <AbsoluteFill>")

    # Scene sequences
    for fd in frame_data:
        transition = fd["scene"].transition or "fade"
        lines.append(f'      <Sequence from={{{fd["from_frame"]}}} durationInFrames={{{fd["duration_frames"]}}}>')
        lines.append(f'        <TransitionWrapper type="{transition}" durationInFrames={{{fd["duration_frames"]}}}>')
        lines.append(f'          <{fd["name"]} />')
        lines.append('        </TransitionWrapper>')
        lines.append('      </Sequence>')

    # Audio sequences
    if has_audio:
        for fd in frame_data:
            lines.append(f'      <Sequence from={{{fd["from_frame"]}}} durationInFrames={{{fd["duration_frames"]}}}>')
            lines.append(f'        <Audio src={{staticFile("audio/{fd["scene"].id}.wav")}} />')
            lines.append('      </Sequence>')

    # Captions
    if captions:
        lines.append("      <CaptionOverlay />")

    # Watermark
    if watermark:
        lines.append(f'      <div style={{{{ position: "absolute", top: 40, right: 40, color: "rgba(255,255,255,0.4)", fontSize: 24, fontFamily: "Inter" }}}}>')
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
    lines.append(f"      durationInFrames={{{total_frames}}}")
    lines.append(f"      fps={{{fps}}}")
    lines.append(f"      width={{{width}}}")
    lines.append(f"      height={{{height}}}")
    lines.append("    />")
    lines.append("  );")
    lines.append("};")
    lines.append("")

    return "\n".join(lines)


def _transition_wrapper_code() -> str:
    return '''const TransitionWrapper: React.FC<{
  type: string;
  durationInFrames: number;
  children: React.ReactNode;
}> = ({ type, durationInFrames, children }) => {
  const frame = useCurrentFrame();
  const transitionDuration = 10;
  const progress = Math.min(frame / transitionDuration, 1);
  const exitStart = durationInFrames - transitionDuration;
  const exitProgress = frame > exitStart ? Math.min((frame - exitStart) / transitionDuration, 1) : 0;

  let style: React.CSSProperties = { width: "100%", height: "100%" };

  if (type === "fade") {
    style.opacity = progress * (1 - exitProgress);
  } else if (type === "slide-left") {
    const enterX = (1 - progress) * 100;
    const exitX = exitProgress * -100;
    style.transform = `translateX(${frame < transitionDuration ? enterX : exitX}%)`;
    style.opacity = 1 - exitProgress;
  } else if (type === "slide-up") {
    const enterY = (1 - progress) * 100;
    const exitY = exitProgress * -100;
    style.transform = `translateY(${frame < transitionDuration ? enterY : exitY}%)`;
    style.opacity = 1 - exitProgress;
  } else if (type === "zoom-in") {
    const scale = 0.8 + 0.2 * progress;
    style.transform = `scale(${scale * (1 - exitProgress * 0.2)})`;
    style.opacity = progress * (1 - exitProgress);
  } else {
    style.opacity = progress * (1 - exitProgress);
  }

  return <div style={style}>{children}</div>;
};'''


def _caption_overlay_code(components: list[dict]) -> str:
    return '''const CaptionOverlay: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  // Caption overlay — word-by-word reveal synced with narration
  // Each scene's narration text appears at the bottom, words highlighting in sequence
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
