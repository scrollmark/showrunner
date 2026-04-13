import { useCurrentFrame, interpolate } from "remotion";
import { curve, motion } from "../tokens";
import type { CurveName } from "../tokens/schema";

interface EnterOptions {
  /** Delay before the entrance starts, in frames. */
  delayFrames?: number;
  /** Duration of the entrance in frames. Defaults to 15 (~0.5s at 30fps). */
  durationFrames?: number;
  /** Override the preset's enterCurve. */
  curve?: CurveName;
}

/** Returns a 0→1 "progress" value for an entrance animation on the current frame.
 * Intended to drive opacity, translateY, scale, or any other entering property.
 *
 * Scenes MUST prefer this hook over a bare `interpolate(frame, ...)` call.
 */
export function useEnter(opts: EnterOptions = {}): number {
  const frame = useCurrentFrame();
  const {
    delayFrames = 0,
    durationFrames = 15,
    curve: curveName = motion.enterCurve,
  } = opts;
  return interpolate(
    frame - delayFrames,
    [0, durationFrames],
    [0, 1],
    {
      easing: curve(curveName),
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    }
  );
}
