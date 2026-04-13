import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface CenterStackProps {
  /** Small uppercase label above the title (e.g. "STEP 2"). */
  eyebrow?: React.ReactNode;
  /** Primary title text. */
  title: React.ReactNode;
  /** Supporting body copy below the title. */
  body?: React.ReactNode;
  /** Optional accent element (button, badge, stat) below the body. */
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
 * Handles its own entrance + exit animation via the motion kit — the
 * scene never has to think about animating the layout.
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
        {illustration ? <div style={{ marginBottom: spacing.sm }}>{illustration}</div> : null}
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
        {accent ? <div style={{ marginTop: spacing.sm }}>{accent}</div> : null}
      </div>
    </Scene>
  );
}
