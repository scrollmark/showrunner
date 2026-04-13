import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface HeroProps {
  /** Big display-weight text — the whole scene's focal point. */
  display: React.ReactNode;
  /** Optional subtitle below the display. */
  tagline?: React.ReactNode;
  /** Decorative background layer. */
  background?: React.ReactNode;
}

/**
 * A single massive display phrase with an optional tagline. Intended
 * for opening hooks and closing CTAs where the whole message is one
 * or two lines.
 */
export function Hero({ display, tagline, background }: HeroProps) {
  const enter = useEnter({ durationFrames: 30 });
  const exit = useExit({ durationFrames: 18 });
  const vis = enter * exit;
  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: spacing.lg,
          alignItems: "center",
          textAlign: "center",
          maxWidth: "90%",
          opacity: vis,
          transform: `translateY(${(1 - vis) * 16}px)`,
        }}
      >
        <h1 style={{ ...typeStyle("display"), color: colors.text, margin: 0 }}>{display}</h1>
        {tagline ? (
          <p
            style={{
              ...typeStyle("subhead"),
              color: colors.textMuted,
              margin: 0,
              maxWidth: "80%",
            }}
          >
            {tagline}
          </p>
        ) : null}
      </div>
    </Scene>
  );
}
