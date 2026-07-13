# Voiceover Craft

Voice selection and delivery pacing. The voice is the viewer's narrator for
the whole video — a mismatch reads instantly as machine-made.

## Choosing a voice

`showrunner voices` lists what's available; set it at scaffold time
(`showrunner new --voice <id>`) or per-run (`showrunner tts --voice <id>`).

Match the voice to the content's register, not to "sounds nice in
isolation":

- Instructional/explainer → warm, mid-paced, neutral-accent voices; clarity
  beats character.
- Hype/launch/listicle → brighter, higher-energy voices; slight speed-up
  works with them, not against.
- Story/emotional → lower, slower voices; let pauses breathe.

Pick ONE voice per video. Switching voices mid-video is a stunt, not a
default.

## Speed

`--speed` multiplies delivery rate. Useful band: 0.95–1.15.

- 9:16 feed content tolerates (and rewards) 1.05–1.1 — platform viewers are
  acclimated to brisk narration.
- Below 0.95 sounds sedated; above 1.2 sounds glitchy and hurts caption
  sync later.
- Fix pacing in the WRITING first (see `craft/storyboard.md` — tight
  narration, 1–2 sentences per scene). Speed is a trim, not a rewrite.

## Working with measured durations

`showrunner tts` measures real narration lengths and stretches scenes that
run long. If a scene stretched far past its planned duration, the narration
is overwritten — cut words, don't crank speed. Re-run tts after any
narration edit; downstream timing (compose, ducking) reads the measured
durations, not your plan.
