// Load font families referenced by the active preset up-front, scoped
// to ONLY the weights + Latin subset the preset actually uses.
//
// Why scoping matters: Remotion renders frames in parallel Chrome tabs
// (default concurrency = CPU cores - 1). Calling loadFont() with no
// args fetches every weight × every subset of a family — easily 100+
// HTTP requests per tab. Multiply by ~8 tabs and Google Fonts starts
// throttling, which manifests as puppeteer tx_ack_timeout cascades and
// eventually a cryptic "Minified React error" when Chrome dies.
//
// We collect the {family → weights[]} pairs the preset declares, then
// load each family ONCE with that exact weight list + Latin subset.

import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadSpaceGrotesk } from "@remotion/google-fonts/SpaceGrotesk";
import { loadFont as loadFraunces } from "@remotion/google-fonts/Fraunces";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadDMSerif } from "@remotion/google-fonts/DMSerifDisplay";

import { preset } from "./preset.generated";

type FontLoader = (opts?: {
  weights?: string[];
  subsets?: string[];
  style?: "normal" | "italic";
}) => unknown;

const LOADERS: Record<string, FontLoader> = {
  "Inter": loadInter as FontLoader,
  "Space Grotesk": loadSpaceGrotesk as FontLoader,
  "Fraunces": loadFraunces as FontLoader,
  "Playfair Display": loadPlayfair as FontLoader,
  "DM Serif Display": loadDMSerif as FontLoader,
};

// Collect family → unique sorted weights from typography roles.
const familyToWeights = new Map<string, Set<string>>();
for (const role of Object.values(preset.typography)) {
  const family = role.family;
  const weight = String(role.weight);
  if (!familyToWeights.has(family)) familyToWeights.set(family, new Set());
  familyToWeights.get(family)!.add(weight);
}

for (const [family, weights] of familyToWeights) {
  const loader = LOADERS[family];
  if (!loader) continue;
  loader({
    weights: Array.from(weights).sort(),
    subsets: ["latin"],
  });
}
