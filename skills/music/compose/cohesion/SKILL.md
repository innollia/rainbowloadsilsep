---
name: Cohesion
description: 악기들이 한 밴드처럼 들리게: 공유 공간(같은 리버브·딜레이에 보내는 양만 다르게), 역할과 대역 하나씩, 서로 어울리는 소리 고르기
keywords: 안 어울려, 안어울려, 어울리게, 따로 놀아, 따로 들려, 겉돌, 통일감, 일체감, 한 공간, 하나로, 뭉치게, 리버브, 공간감, 산만, 어수선, cohesive, cohesion, glue, blend, fit together, same room, sounds separate, out of place, reverb, send
---

- Cohesion is mostly fundamentals plus parts that belong together; processing can't fix parts that don't sound like one band. If the basics are in place you are 90% done with cohesion.

One shared space:
- Put everything in one shared space: the same reverb (and delay) with the same settings, and vary only how much each part sends; less on drums. If the same reverb is used on multiple elements, they sound like they came from the same room.
- In this engine reverb and delay settings are shared per `.orbit()`. Keep one `.size()` and one `.delaytime()`/`.delayfeedback()` for every track on an orbit and vary only `.room()` and `.delay()`, the send amounts:
  `[drums] stack(s("bd*4").gain(.5), s("~ cp ~ cp").gain(.45).room(.08).size(1.2))`
  `[keys] chord("<Am7 F^7>").voicing().s("triangle").room(.2).size(1.2).gain(.25)`
  `[lead] n("0 ~ 2 4").scale("A:minor").add(note(12)).s("sawtooth").lpf(2200).room(.3).size(1.2).delay(.25).delaytime(.375).delayfeedback(.35).gain(.35)`
- A heavily reverbed melodic part next to dry drums sounds like two separate pieces. Cut the atmospheric reverb down and send the dry parts (drums too, just less) into one short room. It doesn't take a lot; you don't even need to really hear it.
- The shared room should be short (about 0.8-1.5 s, `.size(1)` to `.size(2)`). A shared slap or 8th-note delay does the same job with even less wash. Use one delay time, or rhythmic delay times that tie instruments together, not random settings per instrument.
- Start from dry synths, then add the global effects all synth parts share, instead of each synth carrying its own reverb and delay.
- "If everything is stereo, nothing is": keep some sources mono and pan them.

Roles and bands:
- Every instrument gets one purpose and one frequency range. Think like a band arranger: there is no reason to have 20 synth tracks going on. A good combination is a balanced set of timbres (a bassy sound, a honky keyboard, a bright pluck, a biting guitar) that weave in and out with room to breathe between phrases.
- Parts that snake around each other, never sounding at the same moment, sound busy yet clean without heavy filtering; orchestral composers "EQ" in the writing.
- Contrast comes from processing and role, not from a different universe of sound: pair a mono bass with a wide pad for both focus and width.

Choosing sounds:
- You don't need better sounds; you need sounds that coexist. Judge a sound inside the track, not soloed. Decide whether the track needs warm, bright, dry or wide, and pick to match.
- If a sound just doesn't fit no matter what you do, use a different sound instead of filtering it again and again.
- Signs a sound doesn't fit: a bass sitting in the kick's range; a lead competing with the main focus; a pad filling space other parts need.
- A smaller core instrument set gives a more cohesive sound. In a game, keep one consistent style across the whole soundtrack; a wrong instrument choice can flip a mood (a horror cue turned comical).
