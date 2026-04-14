import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors } from "../tokens";

export interface GridBackgroundProps {
  /** Stroke opacity 0.01–0.2. Defaults to a soft 0.08. */
  opacity?: number;
  /** Grid cell size in pixels. Defaults to 60. */
  cellSize?: number;
  /** Override line color — defaults to primary. */
  strokeColor?: string;
}

/**
 * A faint rectangular grid. Pure decoration — conveys nothing, drifts
 * slowly upward during the scene for a subtle sense of motion.
 */
export function GridBackground({
  opacity = 0.08,
  cellSize = 60,
  strokeColor,
}: GridBackgroundProps) {
  const frame = useCurrentFrame();
  const drift = interpolate(frame, [0, 300], [0, -cellSize], {
    extrapolateLeft: "clamp",
    extrapolateRight: "extend",
  });
  const color = strokeColor ?? colors.primary;
  return (
    <AbsoluteFill style={{ opacity }}>
      <svg
        width="100%"
        height="100%"
        style={{ transform: `translateY(${drift}px)` }}
      >
        <defs>
          <pattern
            id="bg-grid"
            width={cellSize}
            height={cellSize}
            patternUnits="userSpaceOnUse"
          >
            <path
              d={`M ${cellSize} 0 L 0 0 0 ${cellSize}`}
              fill="none"
              stroke={color}
              strokeWidth="1"
            />
          </pattern>
        </defs>
        <rect width="100%" height="200%" fill="url(#bg-grid)" />
      </svg>
    </AbsoluteFill>
  );
}
