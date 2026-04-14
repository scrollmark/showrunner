import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors } from "../tokens";
import type { ColorRoleKey } from "./types";

export interface WavyLinesProps {
  /** Number of wave lines. Default 5. */
  count?: number;
  /** Stroke opacity. Default 0.15. */
  opacity?: number;
  strokeColor?: ColorRoleKey;
}

/**
 * Animated sine-wave lines drifting horizontally. Decorative only;
 * conveys subtle continuous motion without competing with the layout.
 */
export function WavyLines({
  count = 5,
  opacity = 0.15,
  strokeColor = "primary",
}: WavyLinesProps) {
  const frame = useCurrentFrame();
  const tint = colors[strokeColor];
  const phase = interpolate(frame, [0, 240], [0, Math.PI * 2], {
    extrapolateLeft: "clamp",
    extrapolateRight: "extend",
  });
  const lines = Array.from({ length: count }, (_, i) => {
    const yPct = 15 + (i * (70 / Math.max(count - 1, 1)));
    const amplitude = 12 + i * 3;
    const linePhase = phase + i * 0.6;
    const points = Array.from({ length: 40 }, (_, k) => {
      const x = (k / 39) * 100;
      const y = yPct + Math.sin(linePhase + k * 0.3) * amplitude * 0.04;
      return `${x},${y}`;
    }).join(" ");
    return { points, key: i };
  });
  return (
    <AbsoluteFill style={{ opacity }}>
      <svg
        width="100%"
        height="100%"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
      >
        {lines.map((l) => (
          <polyline
            key={l.key}
            points={l.points}
            fill="none"
            stroke={tint}
            strokeWidth="0.2"
          />
        ))}
      </svg>
    </AbsoluteFill>
  );
}
