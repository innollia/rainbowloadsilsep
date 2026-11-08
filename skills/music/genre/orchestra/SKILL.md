---
name: Orchestra and symphony
description: 오케스트라·심포니: 마이너 i-VI-III-VII, 악기군별 음역, 팀파니와 오스티나토, 웅장한 곡
---

Orchestra and symphony, 60-110 bpm, minor i-VI-III-VII, every family in its own register, timpani and ostinato. Grand means many mid and high layers, not low held sines. Saws for strings and brass; sine alone never reads as orchestra.
```strudel bpm=84
[lows] note("<a1 f1 c2 g1>").add(note("0,12")).struct("x ~ x x x ~ x ~").s("sawtooth").attack(.01).decay(.25).sustain(.2).lpf(900).gain(.45)
[strings] chord("<Am F C G>").voicing().add(note("0,12")).s("sawtooth").attack(.25).release(.5).lpf(2600).vib(5).vibmod(.08).superimpose(x=>x.add(note(.1))).gain(.13)
[brass] chord("<Am F C G>").voicing().s("sawtooth").attack(.06).release(.3).lpf(900).lpenv(3).lpa(.08).lpd(.3).lps(.5).mask("<0 1>/4").gain(.25)
[melody] n("<[0 ~ 2 4] [5 4 2 ~] [4 ~ 5 7] [6 ~ 4 ~]>").scale("A:minor").add(note(12)).s("sawtooth").attack(.08).release(.3).lpf(3200).vib(5).vibmod(.12).gain(.3)
[timpani] note("<a1 f1 c2 g1>").struct("x ~ ~ x x ~ ~ ~").s("sine").penv(-4).pdecay(.06).decay(.5).sustain(0).gain(.6)
[perc] s("<cr ~ ~ ~>").gain(.3)
```
