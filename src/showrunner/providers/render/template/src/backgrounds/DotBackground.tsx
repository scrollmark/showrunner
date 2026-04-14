import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors } from "../tokens";

export interface DotBackgroundProps {
  /** 0.01–0.25. Default 0.12. */
  opacity?: number;
  /** Spacing between dots in px. Default 48. */
  spacing?: number;
  /** Dot radius in px. Default 2. */
  radius?: number;
  strokeColor?: string;
}

/**
 * A field of evenly-spaced dots with a slow drift. Decorative only.
 */
export function DotBackground({
  opacity = 0.12,
  spacing = 48,
  radius = 2,
  strokeColor,
}: DotBackgroundProps) {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, 360], [0, -spacing], {
    extrapolateLeft: "clamp",
    extrapolateRight: "extend",
  });
  const color = strokeColor ?? colors.primary;
  return (
    <AbsoluteFill style={{ opacity }}>
      <svg
        width="100%"
        height="100%"
        style={{ transform: `translate(${drift}px, ${drift}px)` }}
      >
        <defs>
          <pattern
            id="bg-dots"
            width={spacing}
            height={spacing}
            patternUnits="userSpaceOnUse"
          >
            <circle cx={spacing / 2} cy={spacing / 2} r={radius} fill={color} />
          </pattern>
        </defs>
        <rect width="200%" height="200%" fill="url(#bg-dots)" />
      </svg>
    </AbsoluteFill>
  );
}
