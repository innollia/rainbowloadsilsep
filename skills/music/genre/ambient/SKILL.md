---
name: Ambient
description: 앰비언트: 드럼 없이 느린 패드, 긴 딜레이, 드문 벨
keywords: 앰비언트, ambient
---

Ambient, 60-80 bpm, no drums, slow drifting pads, long delays, sparse bells.
```strudel bpm=70
[pad] chord("<C^9 Am9 F^9 G6>").voicing().slow(2).s("sawtooth").attack(1.5).release(2).lpf(sine.range(500,1400).slow(16)).pan(sine.slow(7)).gain(.38)
[texture] s("padlong").slow(4).gain(.35)
[bells] n("0 ~ 4 ~ ~ 7 ~ ~").scale("C:major:pentatonic").add(note(24)).s("triangle").fm(3).fmh(3.5).decay(.8).sustain(0).delay(.6).delaytime(.64).delayfeedback(.6).sometimes(degrade).gain(.45)
[air] s("pink").slow(2).lpf(900).attack(2).release(2).gain(.3)
```
