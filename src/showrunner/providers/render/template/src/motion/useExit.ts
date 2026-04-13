import { useCurrentFrame, useVideoConfig, interpolate } from "remotion";
import { curve, motion } from "../tokens";
import type { CurveName } from "../tokens/schema";

interface ExitOptions {
  /** Duration of the exit in frames. Defaults to 15. */
  durationFrames?: number;
  /** Override the preset's exitCurve. */
  curve?: CurveName;
}

/** Returns a 1→0 "visibility" value for an exit animation, active in the
 * last N frames of the current sequence/composition. Drive opacity,
 * scale, or translateY off this to animate elements out.
 */
export function useExit(opts: ExitOptions = {}): number {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const { durationFrames = 15, curve: curveName = motion.exitCurve } = opts;
  const exitStart = durationInFrames - durationFrames;
  return interpolate(
    frame,
    [exitStart, durationInFrames],
    [1, 0],
    {
      easing: curve(curveName),
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }
  );
}
