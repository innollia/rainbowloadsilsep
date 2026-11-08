---
name: Groove
description: 그루브와 엇박: 앵커를 박에 고정하고 한 요소씩 당기기, 엇박 변형, 킥-베이스 맞물림, 스탭·컴핑 패턴
keywords: 그루브, 엇박, 당김음, 싱코페이션, 리듬, 박자, 뻣뻣, 딱딱, 기계, 밋밋, 따로 놀아, 킥, 베이스, 스탭, groove, syncopation, syncopate, offbeat, stiff, robotic, pocket, kick, bass, stab, comping
---

Groove is not a setting. It is a system: timing, velocity and placement working together.

Anchor first:
- Syncopation creates tension. Notes landing *between* the grid set up resolution: the brain anticipates the downbeat and the off-hit releases it.
- Keep one anchor on the beat (kick on 1, or snare on 2 and 4) and syncopate around it. If every sound is off the beat, the listener loses the pulse and the pattern reads as random instead of groovy. If every element is syncopated, nothing is.
- Build a straight reference first, then move one hit at a time. One displaced hit is often enough. Add ONE syncopated element at a time and lock it to the drums before adding another. Random off-beat notes aren't syncopation; they're just messy.
- Keep one anchor between parts too: if the chords syncopate, keep the bass on downbeats (or vice versa). Don't syncopate every layer the same way; complementary rhythms (call/response between bass and stabs) sound tighter than everyone pushing together.
- Add a counter-pulse (a hat on every "and") so displaced hits have something to play against: `s("[~ hh]*4")`. 8ths-on-the-downbeat hats with nothing on the offbeats are the most common cause of "stiff" patterns.
- Mute test: when a groove feels off, the culprit is often not the drums but another part fighting it (for example a pad on straight quarter notes).

Syncopate a single step by replacing `x` with `[~ x]` (delayed entry), `[x ~]` (early cutoff), `[x@2 ~]`, `[~ x@2]` or `[~ ~ x]` (late entry). Pick a few steps; do not syncopate every note or the rhythm becomes too busy: `n("0 2 [~ 4] 2 [0 ~] 2 [~ 4@2] 7").scale("C:minor")`.

Kick-bass lock:
- The bass note onset lands *with* the kick or *just after*, never ahead. Bass note on the kick = root or 5th; notes between kicks can move.
- Shorten bass notes on kick beats; write the bass to release when the kick hits.
- Entwine the bass around the kick so they don't hit together ("snaking the bass around the kick"). But if every bass note is off-beat it sounds like one specific style; groove comes from the mix of syncopated and on-beat bass notes. The bass should answer the displaced hit, not fight it.
- A syncopated bassline with no rhythmic relationship to the kick creates a muddy low end with no pocket.
Kick `s("bd ~ ~ bd ~ ~ bd ~")` with bass `note("a1 ~ ~ e2 ~ [~ c2] a1 ~").s("sawtooth").lpf(500).decay(.15).sustain(.3)`

Stabs and comping, one bar of a chord with `.struct()`:
- Off-beat chord stabs on the "and" of 2 and 4, short and punchy. Too long, and it muddles the groove. Too quiet, and it gets lost: `.struct("~ ~ ~ x ~ ~ ~ x")`.
- House offbeat 8ths `"[~ x]*4"`; deep house push `"x ~ ~ x ~ ~ x ~ ~ ~ x ~ ~ ~ ~ ~"`; Charleston `"x ~ ~ x ~ ~ ~ ~"`; soul comp `"x ~ ~ ~ ~ ~ x ~ ~ ~ ~ x ~ ~ ~ ~"`; garage skip `"x ~ ~ x ~ ~ ~ ~ ~ x ~ ~ x ~ ~ ~"`; DnB two-step stab with the kick `"x ~ ~ ~ ~ x ~ ~"`.
- Anticipation ("the push"): moving a chord change an 8th or 16th early gives funk, soul and house their forward lean: `chord("<Am7 F^7>").voicing().early(1/8)`.
