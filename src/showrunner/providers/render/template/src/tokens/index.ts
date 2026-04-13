// Import for side effects — registers every font family used by the preset.
import "./fonts";

export { preset } from "./preset.generated";
export type { Preset, TypeRole, TypeRoleKey, CurveName } from "./schema";
export { curve } from "./easing";
export { typeStyle, typography } from "./typography";
export { framesPerBeat, beatsToFrames, sceneFrames, transitionFrames } from "./rhythm";

import { preset as _preset } from "./preset.generated";
export const colors = _preset.colors;
export const spacing = _preset.spacing;
export const rhythm = _preset.rhythm;
export const motion = _preset.motion;
