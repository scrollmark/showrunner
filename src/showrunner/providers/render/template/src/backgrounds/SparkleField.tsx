import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { colors } from "../tokens";
import type { ColorRoleKey } from "./types";

export interface SparkleFieldProps {
  /** Number of sparkles. Default 12. */
  count?: number;
  /** Palette role used to tint sparkles. Default "accent". */
  color?: ColorRoleKey;
  /** Sparkle radius in px. Default 4. */
  radius?: number;
}

/**
 * Decorative field of twinkling sparkles, distributed with a fixed
 * seed so the layout is stable per render.
 */
export function SparkleField({
  count = 12,
  color = "accent",
  radius = 4,
}: SparkleFieldProps) {
  const frame = useCurrentFrame();
  const tint = colors[color];
  const sparkles = Array.from({ length: count }, (_, i) => {
    const seed = (i * 9301 + 49297) % 233280;
    const x = (seed / 233280) * 100;
    const y = ((seed * 3 + 17) % 100);
    const delay = (i * 12) % 90;
    const phase = (frame - delay) % 60;
    const opacity = phase < 0 ? 0 : interpolate(phase, [0, 20, 40, 60], [0, 0.8, 0.8, 0]);
    const scale = phase < 0 ? 0 : interpolate(phase, [0, 20, 40, 60], [0, 1, 1, 0]);
    return { x, y, opacity, scale, key: i };
  });
  return (
    <AbsoluteFill>
      {sparkles.map((s) => (
        <div
          key={s.key}
          style={{
            position: "absolute",
            left: `${s.x}%`,
            top: `${s.y}%`,
            width: radius * 2,
            height: radius * 2,
            borderRadius: "50%",
            background: tint,
            opacity: s.opacity,
            transform: `scale(${s.scale})`,
          }}
        />
      ))}
    </AbsoluteFill>
  );
}
