// Load every font family referenced by the active preset up-front so that
// scene renders don't flash unstyled text. Each @remotion/google-fonts
// import side-effects the font registration.
//
// This file is imported from `index.ts` for its side effects only.

import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadSpaceGrotesk } from "@remotion/google-fonts/SpaceGrotesk";
import { loadFont as loadFraunces } from "@remotion/google-fonts/Fraunces";
import { loadFont as loadPlayfair } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadDMSerif } from "@remotion/google-fonts/DMSerifDisplay";

import { preset } from "./preset.generated";

const LOADERS: Record<string, () => void> = {
  "Inter": () => loadInter(),
  "Space Grotesk": () => loadSpaceGrotesk(),
  "Fraunces": () => loadFraunces(),
  "Playfair Display": () => loadPlayfair(),
  "DM Serif Display": () => loadDMSerif(),
};

const loaded = new Set<string>();
for (const role of Object.values(preset.typography)) {
  const family = role.family;
  if (loaded.has(family)) continue;
  loaded.add(family);
  const loader = LOADERS[family];
  if (loader) loader();
}
