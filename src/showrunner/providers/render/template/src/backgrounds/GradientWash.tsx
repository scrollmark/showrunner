import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors } from "../tokens";
import type { ColorRoleKey } from "./types";

export interface GradientWashProps {
  /** Palette role to start from. Default "background". */
  from?: ColorRoleKey;
  /** Palette role to end at. Default "primary". */
  to?: ColorRoleKey;
  /** Gradient angle in degrees. Default 135. */
  angle?: number;
  /** Opacity of the wash over the base background. Default 0.18. */
  opacity?: number;
  /** If true, the gradient slowly rotates across the scene duration. */
  animate?: boolean;
}

/**
 * A soft linear-gradient wash between two palette colors. Decorative
 * only — provides atmospheric color variation behind the layout.
 */
export function GradientWash({
  from = "background",
  to = "primary",
  angle = 135,
  opacity = 0.18,
  animate = true,
}: GradientWashProps) {
  const frame = useCurrentFrame();
  const rotation = animate
    ? interpolate(frame, [0, 300], [angle, angle + 20], {
        extrapolateLeft: "clamp",
        extrapolateRight: "extend",
      })
    : angle;
  const fromColor = colors[from];
  const toColor = colors[to];
  return (
    <AbsoluteFill
      style={{
        background: `linear-gradient(${rotation}deg, ${fromColor}, ${toColor})`,
        opacity,
      }}
    />
  );
}
