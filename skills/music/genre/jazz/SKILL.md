---
name: Jazz
description: 재즈: 스윙 라이드, 워킹 베이스, ii-V-I
---

Jazz, 90-180 bpm, ride swing, walking bass, ii-V-I shells.
```strudel bpm=140
[drums] stack(s("linnhats linnhats*2 linnhats linnhats*2").gain(.2), s("~ hh ~ hh").gain(.5), s("bd ~ ~ ~").gain(.3)).swingBy(1/6,4)
[bass] note("<[d2 f2 a2 c3] [g2 b2 d3 f3] [c2 e2 g2 b2] [a1 c#2 e2 g2]>").s("triangle").lpf(900).decay(.4).sustain(.3).gain(.6)
[comp] chord("<Dm9 G13 C^9 A7>").voicing().struct("~ x ~ ~ ~ x ~ ~").s("triangle").fm(1).fmh(3).decay(.4).sustain(.1).lpf(3000).gain(.4)
[lead] n("<[4 ~ 6 7] [8 7 6 ~] [4 2 ~ 0] ~>").scale("C:major").s("square").attack(.03).lpf(2500).vib(5).vibmod(.1).gain(.42)
```
