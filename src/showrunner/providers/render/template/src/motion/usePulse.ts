import { useCurrentFrame, spring, useVideoConfig } from "remotion";
import { motion } from "../tokens";

interface PulseOptions {
  /** Frame the pulse starts at. */
  atFrame: number;
  /** How much the value peaks above 1. `amount: 0.08` → peaks at 1.08. */
  amount?: number;
  /** Spring damping; lower = more bounce. */
  damping?: number;
}

/** Returns a scalar that briefly rises above 1.0 and settles back, for
 * emphasis pulses on stats, titles, or counters at a specific moment.
 */
export function usePulse(opts: PulseOptions): number {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { atFrame, amount = 0.08, damping = 12 } = opts;
  const _curve = motion.pulseCurve; // reserved for future use
  void _curve;
  const s = spring({
    frame: frame - atFrame,
    fps,
    config: { damping, stiffness: 180, mass: 0.6 },
    durationInFrames: Math.round(fps * 0.8),
  });
  // 0→1 spring → 1→(1+amount)→1 scalar with a gentle settle.
  const peak = 1 + amount;
  const rising = 1 + (peak - 1) * s;
  // After the peak, decay back to 1. Using a second spring inverted.
  const decay = spring({
    frame: frame - atFrame - Math.round(fps * 0.2),
    fps,
    config: { damping: 18, stiffness: 140, mass: 0.6 },
  });
  return rising - (peak - 1) * decay;
}
