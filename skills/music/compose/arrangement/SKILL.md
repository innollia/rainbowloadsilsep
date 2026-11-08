---
name: Arrangement
description: 음역 나누기, 긴 곡 구성, 반복 변주, 긴장과 해소, 섹션 나누기, '더'를 요청받았을 때 층 쌓기
---

- Registers, each part with its own place: sub/bass (c1-c3), harmony (c3-c5), lead (c4-c6), air (hats, noise). Never stack two parts in the same octave at the same level.
- Long form: give each track `<>` with long patterns, `.slow(8)`, or `.mask("<0 0 1 1>/4")` so parts enter and leave.
- Variation: `.every(4,fast(2))`, `.sometimes(x=>x.add(note(12)))`, `.lastOf(4,rev)`, `.degradeBy(.2)`, `.rarely(ply(2))`.
- Tension: rising filter `.lpf(saw.range(500,4000).slow(16))`, thinner bass, higher register, faster hats. Release: full stack on a downbeat, lower register, one bar of silence before it.
- Song sections in one track: `arrange([4,s("bd*2")],[4,s("bd*4,hh*8")])`.
- Every request for "more" means new layers with different rhythm and register, not longer held notes.
