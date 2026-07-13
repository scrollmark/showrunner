# HTML Composition Craft (hyperframes runtime)

The composition is ONE `index.html`: DOM elements with `data-*` timing
attributes plus a single paused animation timeline. The renderer seeks every
frame deterministically — anything time-dependent outside the timeline is a
bug the check will catch.

## Structure contract

```html
<div id="root"
     data-composition-id="main"
     data-start="0" data-duration="12"
     data-width="1080" data-height="1920">

  <div id="line_one" class="clip"
       data-start="0" data-duration="4" data-track-index="1">SHIP</div>

  <audio src="assets/audio/vo.wav"
         data-start="0" data-duration="12" data-track-index="2" data-volume="1"></audio>
</div>

<script>
  window.__timelines = window.__timelines || {};
  const tl = gsap.timeline({ paused: true });
  tl.from("#line_one", { opacity: 0, y: -80, duration: 0.6, ease: "back.out(1.7)" }, 0);
  window.__timelines["main"] = tl;
</script>
```

- Every visible element is a `class="clip"` child of the composition root
  with `data-start` / `data-duration` in SECONDS. Overlap clips by putting
  them on different `data-track-index` values.
- Exactly ONE `gsap.timeline({ paused: true })` registered synchronously at
  `window.__timelines["<composition-id>"]`. Timeline position offsets (the
  third arg) are absolute seconds on the same clock as `data-start`.
- Render duration = the root's `data-duration`, not the timeline length.
- `<video>`/`<audio>` elements: direct children of the composition root,
  playback owned by the framework via their `data-*` attributes — never
  `.play()` them yourself.

## Determinism rules (violations fail `showrunner check`)

- No wall clocks: `Date.now()`, `performance.now()`, `setInterval`,
  `requestAnimationFrame` for animation.
- No unseeded randomness — precompute values or seed deterministically.
- No network fetches at seek time (head `<script src>` for the runtime is
  fine; runtime code loads before capture).
- No `repeat: -1` — express repetition in a finite count that fits the
  duration.
- Animate the visual-property allowlist (transforms, opacity, filters,
  clip-path…) — never `display`/`visibility`.

## Craft

- **Beat grid first.** Decide BPM, compute the beat (`60/bpm`), and snap
  every `data-start` and timeline offset to it.
- **Hierarchy through scale + weight.** Two type sizes, one accent color;
  emphasis comes from timing, not from more styles.
- **Enter, hold, exit.** Every clip needs all three thought through — a clip
  that pops in and then sits dead for 3 seconds reads unfinished. Subtle
  drift or scale during holds keeps frames alive.
- **Ease with intent.** `power2.out` and up for entrances; a single
  `back.out` overshoot as the signature moment; linear only for continuous
  drift.
- **Safe margins.** Keep text inside ~8% margins on every side — platform UI
  overlays chew the edges.
