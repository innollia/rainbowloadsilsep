---
name: Sounds
description: 쓸 수 있는 신스·샘플·드럼·텍스처 이름
---

Synths: sawtooth (bright, strings, brass), square (hollow, reeds, chiptune), triangle (soft, flute, keys), sine (sub bass only, nearly inaudible on small speakers), white, pink, brown (noise).
Samples in tune with `note()`: gtr, arpy, juno, moog, bass1. Other pitched samples (pluck, sax, sitar, bass, bass3, jvbass, notes, casio, stab, hoover) are off-key under `note()`: use them as colour on single hits, never for melody or chords.
Drums: kicks bd clubkick hardkick reverbkick 808bd; snares sd sn cp realclaps 808sd rs; hats hh linnhats ho 808oh 808hc; cymbals cr 808cy; toms lt mt ht; other cb perc tabla jazz house gretsch; loops breaks125 breaks152 amencutup (`s("breaks125").fit()`, or `s("amencutup*8").n("0 1 2 3 4 5 6 7")`).
There is no oh, rd, or rim. Use ho, 808cy, and rs.
Textures: pad padlong wind breath birds space (no `note()`).
Pick variants with `.n()` or `s("gtr:2")`. A sample's first play may arrive late.
