import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface QuoteProps {
  text: React.ReactNode;
  attribution?: React.ReactNode;
  background?: React.ReactNode;
}

/**
 * Pullquote layout: oversized opening quote mark, quote text centered,
 * small attribution below. For testimonials, social proof, or dramatic
 * one-liners.
 */
export function Quote({ text, attribution, background }: QuoteProps) {
  const enter = useEnter({ durationFrames: 30 });
  const exit = useExit({ durationFrames: 18 });
  const vis = enter * exit;
  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: spacing.md,
          alignItems: "center",
          textAlign: "center",
          maxWidth: "85%",
          opacity: vis,
          transform: `translateY(${(1 - vis) * 24}px)`,
        }}
      >
        <div
          style={{
            ...typeStyle("display"),
            color: colors.primary,
            margin: 0,
            lineHeight: 0.8,
          }}
        >
          {"\u201C"}
        </div>
        <div style={{ ...typeStyle("title"), color: colors.text, margin: 0 }}>{text}</div>
        {attribution ? (
          <div
            style={{
              ...typeStyle("caption"),
              color: colors.textMuted,
              margin: 0,
              marginTop: spacing.md,
            }}
          >
            — {attribution}
          </div>
        ) : null}
      </div>
    </Scene>
  );
}
