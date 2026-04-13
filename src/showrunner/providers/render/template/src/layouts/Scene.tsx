import React from "react";
import { AbsoluteFill } from "remotion";
import { colors, spacing } from "../tokens";

interface SceneProps {
  /** Primary content: typically a layout-specific content row/column.
   * The outer Scene handles absolute positioning, background color, and
   * a safe content area with `overflow: hidden`. */
  children: React.ReactNode;
  /** Optional decorative layer — rendered BEHIND the content, clipped
   * to the scene bounds. This is the only sanctioned place for
   * freeform `position: absolute` JSX in scene code. */
  background?: React.ReactNode;
}

/**
 * Root of every scene. Every layout primitive wraps its content in
 * <Scene>. Scenes never render <AbsoluteFill> directly — they return
 * one of the layout components, which in turn renders <Scene>.
 *
 * Layering (z-order low → high):
 *   1. `colors.background` fill
 *   2. `background` prop (decorative, clipped)
 *   3. children (the layout's content area)
 */
export function Scene({ children, background }: SceneProps) {
  return (
    <AbsoluteFill style={{ background: colors.background }}>
      {background ? (
        <AbsoluteFill style={{ overflow: "hidden" }}>{background}</AbsoluteFill>
      ) : null}
      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          padding: spacing.lg,
          overflow: "hidden",
        }}
      >
        {children}
      </AbsoluteFill>
    </AbsoluteFill>
  );
}
