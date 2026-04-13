import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface StatBigProps {
  /** If a number, animates with a count-up on entrance. String is shown as-is. */
  value: number | string;
  /** Short label describing the stat (e.g. "creators using Showrunner"). */
  label: string;
  /** Optional prefix before the value (e.g. "+"). */
  prefix?: string;
  /** Optional suffix after the value (e.g. "%" or "x"). */
  suffix?: string;
  /** Optional caption below the label for extra context. Plain text. */
  caption?: string;
  /** Decorative background layer. */
  background?: React.ReactNode;
}

/**
 * A big headline stat. Numeric values animate up from zero; string
 * values render immediately.
 */
export function StatBig({
  value,
  label,
  prefix = "",
  suffix = "",
  caption,
  background,
}: StatBigProps) {
  const enter = useEnter({ durationFrames: 30 });
  const exit = useExit({ durationFrames: 18 });
  const vis = enter * exit;
  const displayValue =
    typeof value === "number" ? Math.round(enter * value).toLocaleString() : value;
  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: spacing.md,
          alignItems: "center",
          textAlign: "center",
          opacity: vis,
          maxWidth: "90%",
        }}
      >
        <div style={{ ...typeStyle("display"), color: colors.primary, margin: 0 }}>
          {prefix}
          {displayValue}
          {suffix}
        </div>
        <div style={{ ...typeStyle("subhead"), color: colors.text, margin: 0 }}>{label}</div>
        {caption ? (
          <div
            style={{
              ...typeStyle("body"),
              color: colors.textMuted,
              margin: 0,
              maxWidth: "70%",
              marginTop: spacing.sm,
            }}
          >
            {caption}
          </div>
        ) : null}
      </div>
    </Scene>
  );
}
