---
name: Hip-hop and lofi
description: 힙합·로파이: 70-90 bpm 스윙 드럼, 재즈 세븐스, 부드러운 건반, 잡음
keywords: 힙합, 로파이, hip-hop, hiphop, lofi, lo-fi
---

Hip-hop and lofi, 70-90 bpm, swung lazy drums, jazzy sevenths, soft keys, crackle.
```strudel bpm=80
[drums] stack(s("bd ~ ~ bd ~ ~ bd ~").gain(.45), s("~ cp").gain(.45), s("hh*8").gain(.5), s("linnhats*4").gain(.12)).swingBy(1/8,4)
[keys] chord("<Dm9 G7 C^7 A7>").voicing().s("triangle").fm(1).fmh(4).attack(.01).decay(.8).sustain(.2).lpf(2600).gain(.45)
[bass] chord("<Dm9 G7 C^7 A7>").rootNotes(2).struct("x ~ ~ x ~ ~ ~ ~").s("triangle").lpf(500).gain(.42)
[vinyl] s("white").hpf(5000).gain(.02)
```
