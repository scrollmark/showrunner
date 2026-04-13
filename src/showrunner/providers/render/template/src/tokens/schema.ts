// Type shape for the active style preset. The concrete values live in
// `preset.generated.ts`, written by the Python pipeline at setup time.
// All scene code imports from `@/tokens` (the index re-exports).

export type TypeRoleKey =
  | "display"
  | "title"
  | "subhead"
  | "body"
  | "caption"
  | "label";

export interface TypeRole {
  family: string;
  weight: number;
  size: number;
  lineHeight: number;
  tracking?: number;
  uppercase?: boolean;
  italic?: boolean;
}

export type CurveName =
  | "out-cubic"
  | "out-quart"
  | "out-expo"
  | "in-cubic"
  | "in-quart"
  | "in-expo"
  | "in-out-cubic"
  | "in-out-quart"
  | "in-out-expo"
  | "overshoot"
  | "back-out";

export interface Preset {
  name: string;
  description: string;
  colors: {
    background: string;
    primary: string;
    secondary: string;
    accent: string;
    text: string;
    textMuted: string;
  };
  typography: Record<TypeRoleKey, TypeRole>;
  spacing: { xs: number; sm: number; md: number; lg: number; xl: number };
  rhythm: { bpm: number; beatsPerScene: number; transitionBeats: number; fps: number };
  motion: {
    enterCurve: CurveName;
    exitCurve: CurveName;
    pulseCurve: CurveName;
    transitionCurve: CurveName;
  };
}
