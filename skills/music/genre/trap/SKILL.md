---
name: Trap
description: 트랩: 130-160 bpm 하프타임, 808, 롤링 하이햇, 어두운 마이너
keywords: 트랩, trap
---

Trap, 130-160 bpm felt in half time, 808 slides, rolling hats, dark minor.
```strudel bpm=140
[drums] stack(s("808bd ~ ~ ~ ~ ~ 808bd ~").gain(.6), s("~ ~ cp ~").gain(.6), s("linnhats*8").gain(.22).every(2,ply("1 1 1 2 1 1 4 1")))
[sub] note("<c2 c2 ab1 g1>").struct("x ~ ~ ~ ~ ~ x ~").s("sine").decay(.9).sustain(.3).add(note("0,12")).gain(.6)
[lead] n("0 ~ 3 ~ 2 ~ -2 ~").scale("C:minor").add(note(24)).s("square").decay(.2).sustain(0).lpf(3500).delay(.3).delaytime(.32).delayfeedback(.4).gain(.42)
```
