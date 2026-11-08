---
name: Rhythm grid
description: 한 곡 한 박 격자, 셋잇단·점8분 쓰는 법, 폴리미터와 폴리리듬이 되는 조건(16스텝 위 3·5스텝, 유클리드 리듬)
keywords: 박 격자, 격자, 박자, 리듬, 셋잇단, 트리플렛, 점8분, 폴리리듬, 폴리미터, 엇갈, 박이 어긋, 박이 안 맞, 따로 놀아, 유클리드, grid, triplet, dotted, polyrhythm, polymeter, cross-rhythm, euclidean, tresillo, off-grid
---

One grid per song:
- One cycle is 4 beats, so an 8th note is 1/8 cycle and a 16th is 1/16. Write every part on the same grid: 4, 8 or 16 steps per cycle (`"x*8"`, `"x*16"`, or 8 or 16 tokens in a pattern).
- A triplet is three equal notes in the space of one beat (`"[x x x]"` per beat, `s("[hh hh hh]*4")`), not "grouping the melody in threes instead of fours".
- Mixing swing and straight grids clashes: swing on the 8ths makes straight 16ths irregular and it doesn't feel right. Pick one consistent swing per part.

Polymeter and polyrhythm:
- In polymeter the grid lines are aligned but the downbeats aren't. In polyrhythm the downbeats are aligned but the grid lines aren't.
- Polyrhythm: two rhythms complete in the same time (3 against 4 lands on the same downbeat). Unstable, dramatic. Polymeter: different-length patterns run at once and their downbeats phase. Hypnotic, evolving.
- The easiest safe polymeter keeps the shared 16th grid and only changes the pattern length of some parts, e.g. a 3- or 5-step line over 16-step drums. Syncopated 16-step drums over three- or five-note lines give a structure that never seems to have a beginning or end: `n("{0 3 7}%16").scale("A:minor")` or `note("{a1 a1 c2 a2 e2}%16")` over `s("bd*4, [~ hh]*4")`.
- Euclidean `(k,n)` spreads k hits over n steps: `(3,8)` is the tresillo, `(5,8)` the son clave basis, `(5,16)` a bossa nova bass, `(7,16)` a dense afrobeat feel. Rotate with a third number: `s("bd(3,8,0), cp(3,8,3)")`. Layered: `s("bd(3,8), hh(7,8), sd(2,8,2)")`.
- 3 against 4 is extremely common in groove music (drums, strums, basslines, melodies). The tresillo (3+3+2) resets every bar, which keeps it from drifting.
- The most common hidden polymeter in 4/4 is a dotted-8th delay over straight 8ths; it fills gaps with fainter echoes. Use `.delaytime()` = 0.75 × 60 / bpm. Dotted 8ths against 4/4 make a 3-against-4 cycle that resolves every 3 beats: `note("{c4 eb4 g4}%16").struct("{x ~ ~}%16")`.

When a cross-rhythm works:
- Anchor: both layers emphasise beat one. There is one main rhythm and one counter-rhythm, and the counter-rhythm notes are of equal value.
- A steady pulse elsewhere is what makes a cross-rhythm readable.
- Triplet hats over straight 8ths can work when the backbeat is rock-solid: snare exactly on 2 and 4 and the first kick of each bar on the grid.
- Decide whether the cross-rhythm is the foundation of the whole song or a section-level device. 2 against 3 (triplet against duplet) is the most common ratio.
- Polymeter parts keep the same tempo. Plan where they realign (3/4 against 7/4 meets after 21 bars) and close the section there. A very short loop makes a polymeter sound like a mistake rather than a choice.
- Polymeter suits rhythmic music; free phasing suits ambient.
