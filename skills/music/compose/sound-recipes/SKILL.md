---
name: Sound recipes
description: 현악·브라스·목관·합창·피아노·패드·팀파니·라이저 같은 악기 음색을 만드는 코드
---

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
