---
name: House
description: 하우스: 120-128 bpm 포온더플로어, 오프비트 하이햇, 마이너 세븐스 스탭
---

House, 120-128 bpm, four-on-floor, offbeat hats, minor seventh stabs, pumping bass.
```strudel bpm=124
[drums] stack(s("bd*4").gain(.36), s("~ cp ~ cp").gain(.5), s("[~ linnhats]*4").gain(.3), s("hh*16").gain(.4))
[bass] note("<a1 a1 f1 g1>").struct("[~ x]*4").s("sawtooth").lpf(500).lpenv(2).lpd(.1).decay(.15).sustain(.4).gain(.36)
[chords] chord("<Am7 Am7 F^7 G7>").voicing().struct("~ x ~ ~ x ~ x ~").s("sawtooth").decay(.2).sustain(.1).lpf(sine.range(800,2500).slow(8)).hpf(200).delay(.3).delaytime(.36).delayfeedback(.4).gain(.55)
```
