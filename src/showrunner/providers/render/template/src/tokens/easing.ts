import { Easing } from "remotion";
import type { CurveName } from "./schema";

// Named curves — every preset's motion.* fields pick from this table.
// Scene code should reference these by name via `useEnter({ curve: motion.enterCurve })`
// rather than importing the concrete Bezier values directly.
const CURVES: Record<CurveName, (t: number) => number> = {
  "out-cubic":    Easing.bezier(0.33, 1,    0.68, 1),
  "out-quart":    Easing.bezier(0.25, 1,    0.5,  1),
  "out-expo":     Easing.bezier(0.16, 1,    0.3,  1),
  "in-cubic":     Easing.bezier(0.32, 0,    0.67, 0),
  "in-quart":     Easing.bezier(0.5,  0,    0.75, 0),
  "in-expo":      Easing.bezier(0.7,  0,    0.84, 0),
  "in-out-cubic": Easing.bezier(0.65, 0,    0.35, 1),
  "in-out-quart": Easing.bezier(0.76, 0,    0.24, 1),
  "in-out-expo":  Easing.bezier(0.87, 0,    0.13, 1),
  "overshoot":    Easing.bezier(0.34, 1.56, 0.64, 1),
  "back-out":     Easing.bezier(0.34, 1.56, 0.64, 1),
};

export function curve(name: CurveName): (t: number) => number {
  return CURVES[name];
}
