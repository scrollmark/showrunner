import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface ComparisonProps {
  leftLabel: string;
  leftContent: string;
  rightLabel: string;
  rightContent: string;
  /** Optional centered string between the panels (typically "vs", "→"). */
  divider?: string;
  background?: React.ReactNode;
}

/**
 * Two-panel comparison: A on the left, B on the right, optional
 * divider in the middle. Labels are small-uppercase; content is
 * subhead-weight. Ideal for "before/after," "old way/new way," etc.
 */
export function Comparison({
  leftLabel,
  leftContent,
  rightLabel,
  rightContent,
  divider,
  background,
}: ComparisonProps) {
  const enter = useEnter({ durationFrames: 24 });
  const rightEnter = useEnter({ delayFrames: 10, durationFrames: 24 });
  const exit = useExit({ durationFrames: 18 });
  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          gap: spacing.lg,
          alignItems: "center",
          justifyContent: "center",
          width: "100%",
          maxWidth: "90%",
        }}
      >
        <Panel
          label={leftLabel}
          content={leftContent}
          labelColor={colors.textMuted}
          opacity={enter * exit}
          offsetX={(1 - enter) * -24}
        />
        {divider ? (
          <div
            style={{
              ...typeStyle("title"),
              color: colors.secondary,
              margin: 0,
              padding: `0 ${spacing.md}px`,
              opacity: enter * exit,
            }}
          >
            {divider}
          </div>
        ) : null}
        <Panel
          label={rightLabel}
          content={rightContent}
          labelColor={colors.primary}
          opacity={rightEnter * exit}
          offsetX={(1 - rightEnter) * 24}
        />
      </div>
    </Scene>
  );
}

function Panel({
  label,
  content,
  labelColor,
  opacity,
  offsetX,
}: {
  label: string;
  content: string;
  labelColor: string;
  opacity: number;
  offsetX: number;
}) {
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        gap: spacing.md,
        alignItems: "center",
        textAlign: "center",
        opacity,
        transform: `translateX(${offsetX}px)`,
      }}
    >
      <div style={{ ...typeStyle("label"), color: labelColor, margin: 0 }}>{label}</div>
      <div style={{ ...typeStyle("subhead"), color: colors.text, margin: 0 }}>{content}</div>
    </div>
  );
}
