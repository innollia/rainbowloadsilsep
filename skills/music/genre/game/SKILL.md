---
name: Game music
description: 게임 음악: 칩튠이나 오케스트라 루프, 짧고 귀에 남는 모티프, 스퀘어와 트라이앵글, 아르페지오
---

Game music, 120-160 bpm chiptune or 90-120 orchestral loop, catchy short motif, square and triangle, arpeggios.
```strudel bpm=150
[lead] n("<[0 2 4 7] [9 7 4 2] [0 4 7 9] [7 ~ 4 ~]>").scale("C:major").add(note(12)).s("square").decay(.12).sustain(.3).lpf(6000).gain(.55)
[arp] chord("<C Am F G>").voicing().arp("0 1 2 3").fast(2).s("square").decay(.08).sustain(0).lpf(4000).gain(.25)
[bass] chord("<C Am F G>").rootNotes(2).struct("x x ~ x x ~ x ~").s("triangle").gain(.4)
[drums] stack(s("bd ~ bd ~").gain(.38), s("~ cp ~ cp").gain(.42), s("linnhats*8").gain(.2))
```
