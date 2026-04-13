import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface CenterStackProps {
  /** Small uppercase label above the title (e.g. "STEP 2"). Plain text only. */
  eyebrow?: string;
  /** Primary title text. Plain text only. */
  title: string;
  /** Supporting body copy below the title. Plain text only. */
  body?: string;
  /** Optional accent element (badge, pill, inline icon) below the body.
   * This slot accepts a React node but is clipped — use for small
   * decorative elements, not full-screen helpers. */
  accent?: React.ReactNode;
  /** Optional illustration rendered ABOVE the title, clipped. */
  illustration?: React.ReactNode;
  /** Decorative background layer (see Scene). */
  background?: React.ReactNode;
  /** Delay the whole stack's entrance animation. */
  enterDelayFrames?: number;
}

/**
 * The workhorse layout. Vertical column, centered, with max-width caps
 * that keep lines readable on both 9:16 and 16:9 aspect ratios.
 * Handles its own entrance + exit animation — scenes never touch layout.
 */
export function CenterStack({
  eyebrow,
  title,
  body,
  accent,
  illustration,
  background,
  enterDelayFrames = 0,
}: CenterStackProps) {
  const enter = useEnter({ delayFrames: enterDelayFrames, durationFrames: 24 });
  const exit = useExit({ durationFrames: 18 });
  const vis = enter * exit;

  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          gap: spacing.md,
          maxWidth: "85%",
          textAlign: "center",
          opacity: vis,
          transform: `translateY(${(1 - vis) * 24}px)`,
        }}
      >
        {illustration ? (
          <SlotBox
            height={320}
            style={{ marginBottom: spacing.sm }}
          >
            {illustration}
          </SlotBox>
        ) : null}
        {eyebrow ? (
          <div style={{ ...typeStyle("label"), color: colors.secondary, margin: 0 }}>{eyebrow}</div>
        ) : null}
        <h1 style={{ ...typeStyle("title"), color: colors.text, margin: 0, maxWidth: "100%" }}>
          {title}
        </h1>
        {body ? (
          <p style={{ ...typeStyle("body"), color: colors.textMuted, margin: 0, maxWidth: "90%" }}>
            {body}
          </p>
        ) : null}
        {accent ? (
          <SlotBox height={80} style={{ marginTop: spacing.sm }}>{accent}</SlotBox>
        ) : null}
      </div>
    </Scene>
  );
}

/** Clipped, positioned container for any ReactNode slot. Stops rogue
 * <AbsoluteFill> children from escaping into the primary content area. */
function SlotBox({
  children,
  height,
  style,
}: {
  children: React.ReactNode;
  height: number;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        position: "relative",
        width: "100%",
        height,
        overflow: "hidden",
        ...style,
      }}
    >
      {children}
    </div>
  );
}
