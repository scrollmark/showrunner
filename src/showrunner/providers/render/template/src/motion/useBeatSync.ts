import { useCurrentFrame } from "remotion";
import { framesPerBeat } from "../tokens";

/** Returns the current beat position as a float. Integer part is the beat
 * index; fractional part is the phase within the beat.
 *
 * Usage:
 *   const beat = useBeatSync();
 *   const onDownbeat = beat - Math.floor(beat) < 0.1; // flash when landing
 */
export function useBeatSync(): number {
  const frame = useCurrentFrame();
  return frame / framesPerBeat();
}

/** True when the current frame is within `window` frames of the given beat. */
export function useIsOnBeat(beatIndex: number, windowFrames = 2): boolean {
  const frame = useCurrentFrame();
  const target = beatIndex * framesPerBeat();
  return Math.abs(frame - target) <= windowFrames;
}
