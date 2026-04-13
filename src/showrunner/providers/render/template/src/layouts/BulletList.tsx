import React from "react";
import { colors, spacing, typeStyle } from "../tokens";
import { useEnter, useExit } from "../motion";
import { Scene } from "./Scene";

export interface BulletListProps {
  title: string;
  items: string[];
  /** Character used as the bullet marker. */
  bulletSymbol?: string;
  background?: React.ReactNode;
}

/**
 * Title + staggered bullets. Each bullet fades and slides in on its
 * own delay so the list reads with rhythm rather than a single pop.
 */
export function BulletList({
  title,
  items,
  bulletSymbol = "•",
  background,
}: BulletListProps) {
  const titleEnter = useEnter({ durationFrames: 24 });
  const exit = useExit({ durationFrames: 18 });
  return (
    <Scene background={background}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: spacing.lg,
          alignItems: "flex-start",
          width: "100%",
          maxWidth: "85%",
        }}
      >
        <h1
          style={{
            ...typeStyle("title"),
            color: colors.text,
            margin: 0,
            opacity: titleEnter * exit,
          }}
        >
          {title}
        </h1>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: spacing.md,
            width: "100%",
          }}
        >
          {items.map((item, i) => (
            <BulletItem
              key={i}
              content={item}
              delayFrames={12 + i * 6}
              bulletSymbol={bulletSymbol}
            />
          ))}
        </div>
      </div>
    </Scene>
  );
}

function BulletItem({
  content,
  delayFrames,
  bulletSymbol,
}: {
  content: string;
  delayFrames: number;
  bulletSymbol: string;
}) {
  const enter = useEnter({ delayFrames, durationFrames: 20 });
  const exit = useExit({ durationFrames: 18 });
  const vis = enter * exit;
  return (
    <div
      style={{
        display: "flex",
        gap: spacing.md,
        alignItems: "baseline",
        opacity: vis,
        transform: `translateX(${(1 - vis) * 24}px)`,
      }}
    >
      <span
        style={{
          ...typeStyle("title"),
          color: colors.accent,
          margin: 0,
          minWidth: 48,
        }}
      >
        {bulletSymbol}
      </span>
      <div style={{ ...typeStyle("body"), color: colors.text, margin: 0 }}>{content}</div>
    </div>
  );
}
