import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface TitleOverContentProps {
  eyebrow?: string;
  title: string;
  /** A React node rendered in a clipped, positioned box below the title.
   * This is the sanctioned place for freeform illustration code. */
  illustration: React.ReactNode;
  background?: React.ReactNode;
}

/**
 * Title block on top + freeform illustration below. The illustration
 * area is clipped to a rounded box so scenes can use any positioning
 * internally without overflowing into the title.
 */
export function TitleOverContent({
  eyebrow,
  title,
  illustration,
  background,
}: TitleOverContentProps) {
  const titleEnter = useEnter({ durationFrames: 24 });
  const illoEnter = useEnter({ delayFrames: 12, durationFrames: 24 });
  const exit = useExit({ durationFrames: 18 });
  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: spacing.lg,
          alignItems: "center",
          width: "100%",
          maxWidth: "92%",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: spacing.sm,
            alignItems: "center",
            textAlign: "center",
            opacity: titleEnter * exit,
          }}
        >
          {eyebrow ? (
            <div style={{ ...typeStyle("label"), color: colors.secondary, margin: 0 }}>
              {eyebrow}
            </div>
          ) : null}
          <h2 style={{ ...typeStyle("title"), color: colors.text, margin: 0 }}>{title}</h2>
        </div>
        <div
          style={{
            position: "relative",
            width: "100%",
            aspectRatio: "16/9",
            overflow: "hidden",
            borderRadius: 16,
            opacity: illoEnter * exit,
            transform: `scale(${0.96 + illoEnter * 0.04})`,
          }}
        >
          {illustration}
        </div>
      </div>
    </Scene>
  );
}
