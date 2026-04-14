// Typed, restricted background primitives. The layout primitives'
// `background` prop accepts only components from this module —
// scene code can NOT inject arbitrary JSX there, which closes the
// "primary content hidden in background slot" escape hatch.

export { GridBackground } from "./GridBackground";
export type { GridBackgroundProps } from "./GridBackground";
export { DotBackground } from "./DotBackground";
export type { DotBackgroundProps } from "./DotBackground";
export { GradientWash } from "./GradientWash";
export type { GradientWashProps } from "./GradientWash";
export { SparkleField } from "./SparkleField";
export type { SparkleFieldProps } from "./SparkleField";
export { WavyLines } from "./WavyLines";
export type { WavyLinesProps } from "./WavyLines";
export type { ColorRoleKey } from "./types";
