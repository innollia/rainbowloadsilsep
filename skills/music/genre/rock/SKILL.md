---
name: Rock
description: 록: 100-140 bpm 백비트, 파워 코드, 8분음표 베이스
keywords: 록, 락, rock
---

Rock, 100-140 bpm, backbeat, power chords, driving eighth bass.
```strudel bpm=120
[drums] stack(s("bd ~ bd ~").gain(.42), s("~ sd ~ cp").gain(.5), s("linnhats*8").gain(.25), s("<cr ~ ~ ~>").gain(.3))
[guitar] note("<e2 e2 c2 d2>").add(note("0,7,12")).struct("x*8").s("gtr").clip(.5).lpf(4000).gain(.2)
[bass] note("<e1 e1 c1 d1>").struct("x*8").s("sawtooth").lpf(450).decay(.15).sustain(.5).gain(.5)
```
