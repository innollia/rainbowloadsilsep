---
name: Sound recipes
description: 현악·브라스·목관·합창·피아노·패드·팀파니·라이저 같은 악기 음색을 만드는 코드, 움직이는 필터와 대역별 레이어
---

A static `lpf` is a tone control. A *moving* lpf is an instrument: `note("c3").s("sawtooth").lpf(400).lpa(.05).lpd(.3).lps(0).lpenv(5)`. Decay + low sustain → pluck. Slow attack + high sustain → swell. Depth (`.lpenv`) controls how dramatic; start at 4. Resonance `.lpq()`: 4-10 adds warmth, 20+ becomes a siren.
Sub / body / air: sub `sine` or `triangle`, no filter; body `sawtooth` or `square` with filter shaping, the character of the sound; air a thin layer of noise or bright triangle. Layer frequency bands, not copies; two bass voices in the same octave fight each other.
`note("c2").s("sine").gain(.5).layer(x=>x.s("sawtooth").lpf(1200).lpenv(3).lpa(.02).lpd(.4).lps(.3), x=>x.s("triangle").hpf(5000).gain(.25))`
Played, not static: filter envelope per note, vibrato `.vib(5).vibmod(.4)`, `.gain(perlin.range(.7,1))`, small drift `.add(note(perlin.range(-.05,.05)))`, `.release(perlin.range(.1,.5))`.

Each is one layer; add `.gain()` and notes.
- Strings: `.s("sawtooth").attack(.25).release(.5).lpf(2200).vib(5).vibmod(.08).superimpose(x=>x.add(note(.1)))`
- Staccato strings: `.s("sawtooth").attack(.01).decay(.12).sustain(0).lpf(3000)`
- Brass: `.s("sawtooth").attack(.06).release(.2).lpf(900).lpenv(3).lpa(.08).lpd(.2).lps(.4)`
- Woodwind: `.s("square").attack(.05).lpf(1800).vib(5).vibmod(.1)`
- Choir: `.s("sawtooth").attack(.3).release(.6).vowel("<a o>").lpf(2500)`
- Electric piano: `.s("triangle").fm(1.5).fmh(4).decay(.5).sustain(.15).release(.3)`
- Piano-like: `.s("triangle").add(note("0,12")).attack(.003).decay(.6).sustain(.1).release(.4).lpf(3500)`
- Pluck, harp: `.s("sawtooth").attack(.002).decay(.18).sustain(0).lpf(1500).lpenv(4).lpd(.1)`
- Soft pad: `.s("triangle").attack(.6).release(1.2).superimpose(x=>x.add(note(.08)).s("sawtooth").lpf(900))`
- Timpani, deep hit: `.s("sine").penv(-6).pdecay(.08).decay(.5).sustain(0)`
- Riser: `s("pink").hpf(saw.range(200,6000).slow(8)).gain(saw.range(.05,.4).slow(8))`
