export { Scene } from "./Scene";
export { CenterStack } from "./CenterStack";
export type { CenterStackProps } from "./CenterStack";
export { Hero } from "./Hero";
export type { HeroProps } from "./Hero";
export { StatBig } from "./StatBig";
export type { StatBigProps } from "./StatBig";
export { BulletList } from "./BulletList";
export type { BulletListProps } from "./BulletList";
export { Quote } from "./Quote";
export type { QuoteProps } from "./Quote";
export { Comparison } from "./Comparison";
export type { ComparisonProps } from "./Comparison";
export { TitleOverContent } from "./TitleOverContent";
export type { TitleOverContentProps } from "./TitleOverContent";

/** Names of all primary layouts. Used by the generated-code linter
 * to verify that scenes import at least one. */
export const LAYOUT_NAMES = [
  "CenterStack",
  "Hero",
  "StatBig",
  "BulletList",
  "Quote",
  "Comparison",
  "TitleOverContent",
] as const;
