---
name: Ballad and K-pop
description: 발라드·케이팝: vi-IV-I-V, 피아노 다음 현악, 후렴에서 올라가기
keywords: 발라드, 케이팝, k-pop, kpop, ballad, pop
---

Ballad and K-pop, 65-85 bpm ballad or 100-125 pop, emotional vi-IV-I-V, piano then strings, chorus lifts.
```strudel bpm=76
[piano] chord("<Am F C G>").voicing().arp("0 1 2 3 2 1 2 1").s("triangle").add(note("0,12")).attack(.003).decay(.6).sustain(.1).lpf(5000).gain(.5)
[strings] chord("<Am F C G>").voicing().add(note(12)).s("sawtooth").attack(.4).release(.6).lpf(3000).vib(5).vibmod(.08).mask("<0 0 1 1>/4").gain(.28)
[bass] chord("<Am F C G>").rootNotes(2).s("triangle").lpf(600).gain(.55)
[drums] stack(s("bd ~ ~ bd ~ bd ~ ~").gain(.5), s("~ cp").gain(.5), s("linnhats*8").gain(.14)).mask("<0 1 1 1>/8")
```
