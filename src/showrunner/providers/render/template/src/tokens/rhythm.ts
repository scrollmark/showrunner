import { preset } from "./preset.generated";

// Beat-grid helpers. All scene/transition timing should go through these
// so the video's cuts land on the underlying musical grid regardless of
// which preset is active.

export function framesPerBeat(): number {
  const { bpm, fps } = preset.rhythm;
  return Math.round((60 / bpm) * fps);
}

export function beatsToFrames(beats: number): number {
  return Math.round(beats * framesPerBeat());
}

export function sceneFrames(): number {
  return beatsToFrames(preset.rhythm.beatsPerScene);
}

export function transitionFrames(): number {
  return beatsToFrames(preset.rhythm.transitionBeats);
}
