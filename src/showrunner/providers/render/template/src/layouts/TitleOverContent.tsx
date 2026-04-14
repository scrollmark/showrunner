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
          height: "100%",
          maxWidth: "92%",
        }}
      >
        <div
          style={{
            flex: "0 0 auto",
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
        {/* Illustration fills the remaining vertical space, full width.
         * No aspect-ratio lock — previously that clipped illustrations
         * when the title ate more vertical space than expected, causing
         * fixed-width terminals / diagrams inside to overflow.
         *
         * The slot itself safe-centers its illustration content: when
         * the content fits, it's centered; when it's taller than the
         * slot, it pins to the top (flex-start fallback) so the top of
         * the illustration is always visible. Without this, LLM-written
         * illustrations with their own `justifyContent: center` would
         * overflow upward past the slot's top edge and get clipped. */}
        <div
          style={{
            position: "relative",
            flex: "1 1 0",
            minHeight: 0,
            width: "100%",
            overflow: "hidden",
            display: "flex",
            alignItems: "safe center",
            justifyContent: "safe center",
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
