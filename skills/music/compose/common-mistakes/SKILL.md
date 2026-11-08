---
name: Common mistakes
description: 초보와 AI가 자주 하는 작곡·편곡 실수: 소리 과다, 진행 없는 루프, 짧고 반복적인 게임 루프, 틀에 박힌 구성, 흔한 멜로디·음색 실수
keywords: 지루해, 지루, 뻔해, 뻔한, 반복, 똑같, 단조, 산만, 복잡, 너무 많, 어색, 아마추어, 초보, 실수, 별로, 이상해, boring, repetitive, generic, cluttered, busy, too much, amateur, mistake, wrong, bland
---

Too much at once:
- Too many sounds competing. Give each sound one clear purpose and cut duplicates. Six synth voices fighting in the same band = mud; three well-separated layers beat six muddy ones.
- Everything sounding at once gives no clarity, and then drastic filtering to compensate. Leave silence between phrases.
- Too many melodies and counter-melodies at once. Over-decoration: so many ornaments that the listener can't find the hook. Strip to the skeleton first, decorate sparingly after.
- Burying the hook in rhythm: an intricate syncopated figure that also has a complex pitch sequence. Simpler pitches when the rhythm is complex; more adventurous pitches when the rhythm is simple.

No arrangement:
- A good loop with no progression is not an arrangement. Plan intros, breakdowns, transitions and the energy build.
- Polishing sounds before the arrangement exists.
- The same drop twice, unchanged. The second peak needs escalation: a new high element, double hat density, a changed bass rhythm.
- A breakdown with no arc is dead air; something should still move, even one filter. An outro longer than the intro leaves the listener stranded.
- The AI-music signature: the same intro-verse-build-drop template, predictable energy curves, flat dynamics. Polish is not identity.

Game music:
- Loops too short and too repetitive. A 30 s loop repeats about 20 times in a 10-minute session. Prefer 1-2 minute loops with internal structure, at least three varying passages: `<>` with long patterns, `.mask()`, or `arrange()`.
- A theme that reuses the same riff within seconds feels more repetitive than its length suggests.
- Background music that grabs too much attention. It should support the game's mood, not create its own. A strong busy melody everywhere fights sound effects and dialogue; save memorable melodies for key moments and use softer, less busy tracks for background. Over-long intros and outros in looping tracks.
- Check the loop seam: tempo or key mismatch between the end and the start.

Melody:
- The wandering line: no repeated motif, no arc, no peak. Cut it to 4 bars, find the best 3-note phrase inside it, make that the motif.
- Resolving too completely too early: cadencing on the root every 2 bars feels like a period at the end of every sentence. End some phrases on the 5th.
- No contrast between phrases: verse and chorus share register, rhythm and contour, so the section change goes unnoticed. Make the chorus higher, simpler and punchier.
- Use one scale or mode per track.

Sound:
- Static filter: `.lpf(1000)` and done sounds like a tone generator. Add `.lpenv(3).lpd(.3)`.
- Default envelopes everywhere: every voice needs a deliberate attack, decay, sustain and release, or it sounds like a preset nobody opened.
- One sawtooth alone is thin; add a second detuned copy: `.superimpose(x=>x.add(note(.1)))`.
- Wrong swing or meter feel for the genre (see Swing and dynamics). All notes the same velocity is the fastest path to "robotic".
