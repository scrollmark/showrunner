# Licensing

Showrunner is MIT-licensed, but a video pipeline is only as free as the tools
it drives. This page explains what Showrunner's license does and does not
cover, and where third-party license obligations apply — most importantly
Remotion, the default render provider.

> **TL;DR:** Showrunner itself is free (MIT). If you render with the default
> `faceless-explainer` format at a for-profit company of **4 or more people**,
> you need a paid Remotion license. The FFmpeg-based `ai-video` format has no
> Remotion license implications.

## Showrunner's license

Showrunner is released under the [MIT License](../LICENSE). You can use,
modify, and redistribute it freely, including commercially.

**Showrunner's license does not grant you any rights to Remotion** (or to any
other third-party provider). Showrunner is a framework that shells out to the
Remotion install in your own project environment — the Remotion license
obligation falls on **whoever runs the render**, not on Showrunner or its
authors. If you use Showrunner in a product or service, you are responsible
for complying with the license terms of every provider you enable.

## Remotion (default render provider)

The `faceless-explainer` format renders video with
[Remotion](https://www.remotion.dev/), which is **source-available, not
open-source**. Remotion's license terms have changed twice in two years;
figures below were verified against
[remotion.dev/docs/license/terms](https://www.remotion.dev/docs/license/terms)
and [remotion.pro/license](https://www.remotion.pro/license) **as of July
2026 (Remotion v5)** — re-check them before relying on this page.

### Who can use Remotion for free

- Individuals working on personal projects
- For-profit companies or teams of **up to 3 people**
- Nonprofit / not-for-profit organizations
- Anyone in an evaluation phase

### Who needs a paid Company License

A paid license is mandatory once the total headcount across all involved
parties reaches **4 or more people** at a for-profit organization using
Remotion beyond evaluation — including for internal tooling.

### Paid tiers relevant to Showrunner users

| Tier | Price | When it applies |
|------|-------|-----------------|
| **Remotion for Creators** | $25/seat/month (no minimum) | Low-volume, human-prompted video creation — e.g. a team member running `showrunner create` by hand |
| **Remotion for Automators** | $0.01/render, $100/month minimum (includes 10,000 renders) | Automated or hosted rendering — **this is the tier that applies to prompt-to-video services** that render on users' behalf |
| **Enterprise** | From $500/month | Custom terms, consulting, private support |

If both Creators and Automators usage apply simultaneously, the $100 monthly
minimum applies with seat spending counting toward it. Remotion's Company
License relies on **accurate self-reporting** of usage.

### Practical guidance

- **Solo creator / team of ≤3:** render freely with the default setup.
- **Company of 4+, humans running the CLI:** you likely need Creators seats.
- **Hosted or automated service** (a web app, bot, or backend that calls
  `Pipeline.run()` to render videos for users): you likely need the
  Automators tier, regardless of how many people are on your team.

When in doubt, consult [remotion.pro](https://www.remotion.pro/license) —
this page is informational, not legal advice.

## The `ai-video` format does not use Remotion

The `ai-video` format assembles AI-generated video clips with **FFmpeg** and
never touches Remotion — **no Remotion license implications on that path**.
FFmpeg itself is free software (LGPL/GPL depending on how your binary was
built); invoking a system-installed `ffmpeg` binary as Showrunner does carries
no per-render fees.

## Other provider terms (one-liners)

Cloud providers each have their own commercial-use terms — check the current
version before shipping:

- **Anthropic / OpenAI (LLM):** API output usage is governed by each vendor's
  commercial API terms.
- **Kokoro (TTS, default):** Apache 2.0 local model — free, including
  commercial use.
- **ElevenLabs (TTS):** a paid plan is required for a commercial license to
  generated audio; see the [ElevenLabs terms](https://elevenlabs.io/terms-of-use).
- **Google Veo via Gemini API (video):** generated video use is governed by
  the [Gemini API additional terms](https://ai.google.dev/gemini-api/terms).
- **MiniMax (video):** commercial use of generated clips is governed by the
  [MiniMax platform terms](https://www.minimax.io/platform/protocol/terms-of-service).

## Summary matrix

| Your setup | Remotion license needed? |
|------------|--------------------------|
| Individual, any format | No |
| Nonprofit, any format | No |
| For-profit ≤3 people, `faceless-explainer` | No |
| For-profit 4+ people, `faceless-explainer`, manual renders | Yes — Creators ($25/seat/mo) |
| Hosted/automated rendering service, `faceless-explainer` | Yes — Automators ($0.01/render, $100/mo min) |
| Any size, `ai-video` (FFmpeg) only | No |
