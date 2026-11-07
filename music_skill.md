# Music craft for this app

Everything here was tested in this app's real audio engine. It overrides general Strudel knowledge.
In examples `[id] code` is one track: only the code goes in the `code` field. One cycle is 4 beats. Use up to 8 tracks.

## Engine limits

<!-- broken -->
Do not write `.drive()`, `.bank()` or `s("bytebeat")`; they do nothing useful here. Any `gm_` or `wt_` sound and `s("piano")` do not exist.
Available effects: `.room()` with `.size()` for reverb, `.shape()` and `.distort()` for saturation, `.crush()`, `.coarse()`, `.phaser()`, `.tremolo()`, and the synths `s("supersaw")`, `s("pulse")`. `.shape()` and `.distort()` raise the level a lot, so lower that track's gain to about half.
<!-- /broken -->

Replacements:
- Space: `.room(.4).size(4)` for a hall, or `.delay(.4).delaytime(.28).delayfeedback(.55)`. Use delaytime 0.75*60/bpm; add `.pan(sine.slow(4))` or `.jux(rev)` for width.
- Thickness: `.superimpose(x=>x.add(note(.12)))` makes a detuned double (`.detune()` is not audible at small values); `.add(note("0,12"))` adds an octave.
- Tremolo and repeated-note strings: `.segment(16).gain(sine.range(.3,.5).fast(4))`.
- Edge: `.lpf(1200).lpenv(3).lpa(.01).lpd(.2)`, `.fm(2).fmh(2)`, or `.vowel("a")`.

Also working: `.lpf .hpf .bpf .lpq .attack .decay .sustain .release .vib .vibmod .fm .fmh .penv .pdecay .vowel .compressor .pan .jux .orbit .duck .duckdepth .velocity .clip .chop .fit`.

## Sounds

Synths: sawtooth (bright, strings, brass), square (hollow, reeds, chiptune), triangle (soft, flute, keys), sine (sub bass only, nearly inaudible on small speakers), white, pink, brown (noise).
Samples in tune with `note()`: gtr, arpy, juno, moog, bass1. Other pitched samples (pluck, sax, sitar, bass, bass3, jvbass, notes, casio, stab, hoover) are off-key under `note()`: use them as colour on single hits, never for melody or chords.
Drums: kicks bd clubkick hardkick reverbkick 808bd; snares sd sn cp realclaps 808sd rs; hats hh linnhats ho 808oh 808hc; cymbals cr 808cy; toms lt mt ht; other cb perc tabla jazz house gretsch; loops breaks125 breaks152 amencutup (`s("breaks125").fit()`, or `s("amencutup*8").n("0 1 2 3 4 5 6 7")`).
There is no oh, rd, or rim. Use ho, 808cy, and rs.
Textures: pad padlong wind breath birds space (no `note()`).
Pick variants with `.n()` or `s("gtr:2")`. A sample's first play may arrive late.

## Sound recipes

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

## Harmony and melody

- Key: `n("0 2 4 7").scale("C:minor")`. Scale names: major minor dorian mixolydian lydian phrygian "minor:pentatonic" "major:pentatonic" blues. Scale degrees cannot go out of key, so prefer them for melodies.
- Chords: `chord("<Am7 F^7 C^7 G7>").voicing()` gives smooth voice leading. Symbols: `Am7 Dm9 G7 C^7 F^7 Bb^7 Asus4 Cadd9`.
- Bass from chords: `chord("<Am F C G>").rootNotes(2)`.
- Arpeggio: `chord("<Am F>").voicing().arp("0 1 2 1")`.
- Progressions: pop I-V-vi-IV; emotional vi-IV-I-V; jazz ii-V-I; epic minor i-VI-III-VII; dark i-iv-VI-V; lofi IVmaj7-iiim7-iim7-Imaj7.
- Bass moves on chord changes and stays out of the melody's rhythm. Melody uses chord tones on strong beats and steps between; leave rests. Answer a 2-bar phrase with a varied 2-bar phrase.
- Counterpoint: when melody rises let a second line fall; `.off(1/8,x=>x.add(note(12)))` gives an echo line; `.rev()` or a slower copy gives a counter-line.

## Arrangement

- Registers, each part with its own place: sub/bass (c1-c3), harmony (c3-c5), lead (c4-c6), air (hats, noise). Never stack two parts in the same octave at the same level.
- Long form: give each track `<>` with long patterns, `.slow(8)`, or `.mask("<0 0 1 1>/4")` so parts enter and leave.
- Variation: `.every(4,fast(2))`, `.sometimes(x=>x.add(note(12)))`, `.lastOf(4,rev)`, `.degradeBy(.2)`, `.rarely(ply(2))`.
- Tension: rising filter `.lpf(saw.range(500,4000).slow(16))`, thinner bass, higher register, faster hats. Release: full stack on a downbeat, lower register, one bar of silence before it.
- Song sections in one track: `arrange([4,s("bd*2")],[4,s("bd*4,hh*8")])`.
- Every request for "more" means new layers with different rhythm and register, not longer held notes.

## Genre recipes

House, 120-128 bpm, four-on-floor, offbeat hats, minor seventh stabs, pumping bass.
```strudel bpm=124
[drums] stack(s("bd*4").gain(.36), s("~ cp ~ cp").gain(.5), s("[~ linnhats]*4").gain(.3), s("hh*16").gain(.4))
[bass] note("<a1 a1 f1 g1>").struct("[~ x]*4").s("sawtooth").lpf(500).lpenv(2).lpd(.1).decay(.15).sustain(.4).gain(.36)
[chords] chord("<Am7 Am7 F^7 G7>").voicing().struct("~ x ~ ~ x ~ x ~").s("sawtooth").decay(.2).sustain(.1).lpf(sine.range(800,2500).slow(8)).hpf(200).delay(.3).delaytime(.36).delayfeedback(.4).gain(.55)
```

Hip-hop and lofi, 70-90 bpm, swung lazy drums, jazzy sevenths, soft keys, crackle.
```strudel bpm=80
[drums] stack(s("bd ~ ~ bd ~ ~ bd ~").gain(.45), s("~ cp").gain(.45), s("hh*8").gain(.5), s("linnhats*4").gain(.12)).swingBy(1/8,4)
[keys] chord("<Dm9 G7 C^7 A7>").voicing().s("triangle").fm(1).fmh(4).attack(.01).decay(.8).sustain(.2).lpf(2600).gain(.45)
[bass] chord("<Dm9 G7 C^7 A7>").rootNotes(2).struct("x ~ ~ x ~ ~ ~ ~").s("triangle").lpf(500).gain(.42)
[vinyl] s("white").hpf(5000).gain(.02)
```

Trap, 130-160 bpm felt in half time, 808 slides, rolling hats, dark minor.
```strudel bpm=140
[drums] stack(s("808bd ~ ~ ~ ~ ~ 808bd ~").gain(.6), s("~ ~ cp ~").gain(.6), s("linnhats*8").gain(.22).every(2,ply("1 1 1 2 1 1 4 1")))
[sub] note("<c2 c2 ab1 g1>").struct("x ~ ~ ~ ~ ~ x ~").s("sine").decay(.9).sustain(.3).add(note("0,12")).gain(.6)
[lead] n("0 ~ 3 ~ 2 ~ -2 ~").scale("C:minor").add(note(24)).s("square").decay(.2).sustain(0).lpf(3500).delay(.3).delaytime(.32).delayfeedback(.4).gain(.42)
```

Rock, 100-140 bpm, backbeat, power chords, driving eighth bass.
```strudel bpm=120
[drums] stack(s("bd ~ bd ~").gain(.42), s("~ sd ~ cp").gain(.5), s("linnhats*8").gain(.25), s("<cr ~ ~ ~>").gain(.3))
[guitar] note("<e2 e2 c2 d2>").add(note("0,7,12")).struct("x*8").s("gtr").clip(.5).lpf(4000).gain(.2)
[bass] note("<e1 e1 c1 d1>").struct("x*8").s("sawtooth").lpf(450).decay(.15).sustain(.5).gain(.5)
```

Jazz, 90-180 bpm, ride swing, walking bass, ii-V-I shells.
```strudel bpm=140
[drums] stack(s("linnhats linnhats*2 linnhats linnhats*2").gain(.2), s("~ hh ~ hh").gain(.5), s("bd ~ ~ ~").gain(.3)).swingBy(1/6,4)
[bass] note("<[d2 f2 a2 c3] [g2 b2 d3 f3] [c2 e2 g2 b2] [a1 c#2 e2 g2]>").s("triangle").lpf(900).decay(.4).sustain(.3).gain(.6)
[comp] chord("<Dm9 G13 C^9 A7>").voicing().struct("~ x ~ ~ ~ x ~ ~").s("triangle").fm(1).fmh(3).decay(.4).sustain(.1).lpf(3000).gain(.4)
[lead] n("<[4 ~ 6 7] [8 7 6 ~] [4 2 ~ 0] ~>").scale("C:major").s("square").attack(.03).lpf(2500).vib(5).vibmod(.1).gain(.42)
```

Ballad and K-pop, 65-85 bpm ballad or 100-125 pop, emotional vi-IV-I-V, piano then strings, chorus lifts.
```strudel bpm=76
[piano] chord("<Am F C G>").voicing().arp("0 1 2 3 2 1 2 1").s("triangle").add(note("0,12")).attack(.003).decay(.6).sustain(.1).lpf(5000).gain(.5)
[strings] chord("<Am F C G>").voicing().add(note(12)).s("sawtooth").attack(.4).release(.6).lpf(3000).vib(5).vibmod(.08).mask("<0 0 1 1>/4").gain(.28)
[bass] chord("<Am F C G>").rootNotes(2).s("triangle").lpf(600).gain(.55)
[drums] stack(s("bd ~ ~ bd ~ bd ~ ~").gain(.5), s("~ cp").gain(.5), s("linnhats*8").gain(.14)).mask("<0 1 1 1>/8")
```

Ambient, 60-80 bpm, no drums, slow drifting pads, long delays, sparse bells.
```strudel bpm=70
[pad] chord("<C^9 Am9 F^9 G6>").voicing().slow(2).s("sawtooth").attack(1.5).release(2).lpf(sine.range(500,1400).slow(16)).pan(sine.slow(7)).gain(.38)
[texture] s("padlong").slow(4).gain(.35)
[bells] n("0 ~ 4 ~ ~ 7 ~ ~").scale("C:major:pentatonic").add(note(24)).s("triangle").fm(3).fmh(3.5).decay(.8).sustain(0).delay(.6).delaytime(.64).delayfeedback(.6).sometimes(degrade).gain(.45)
[air] s("pink").slow(2).lpf(900).attack(2).release(2).gain(.3)
```

Orchestra and symphony, 60-110 bpm, minor i-VI-III-VII, every family in its own register, timpani and ostinato. Grand means many mid and high layers, not low held sines. Saws for strings and brass; sine alone never reads as orchestra.
```strudel bpm=84
[lows] note("<a1 f1 c2 g1>").add(note("0,12")).struct("x ~ x x x ~ x ~").s("sawtooth").attack(.01).decay(.25).sustain(.2).lpf(900).gain(.45)
[strings] chord("<Am F C G>").voicing().add(note("0,12")).s("sawtooth").attack(.25).release(.5).lpf(2600).vib(5).vibmod(.08).superimpose(x=>x.add(note(.1))).gain(.13)
[brass] chord("<Am F C G>").voicing().s("sawtooth").attack(.06).release(.3).lpf(900).lpenv(3).lpa(.08).lpd(.3).lps(.5).mask("<0 1>/4").gain(.25)
[melody] n("<[0 ~ 2 4] [5 4 2 ~] [4 ~ 5 7] [6 ~ 4 ~]>").scale("A:minor").add(note(12)).s("sawtooth").attack(.08).release(.3).lpf(3200).vib(5).vibmod(.12).gain(.3)
[timpani] note("<a1 f1 c2 g1>").struct("x ~ ~ x x ~ ~ ~").s("sine").penv(-4).pdecay(.06).decay(.5).sustain(0).gain(.6)
[perc] s("<cr ~ ~ ~>").gain(.3)
```

Game music, 120-160 bpm chiptune or 90-120 orchestral loop, catchy short motif, square and triangle, arpeggios.
```strudel bpm=150
[lead] n("<[0 2 4 7] [9 7 4 2] [0 4 7 9] [7 ~ 4 ~]>").scale("C:major").add(note(12)).s("square").decay(.12).sustain(.3).lpf(6000).gain(.55)
[arp] chord("<C Am F G>").voicing().arp("0 1 2 3").fast(2).s("square").decay(.08).sustain(0).lpf(4000).gain(.25)
[bass] chord("<C Am F G>").rootNotes(2).struct("x x ~ x x ~ x ~").s("triangle").gain(.4)
[drums] stack(s("bd ~ bd ~").gain(.38), s("~ cp ~ cp").gain(.42), s("linnhats*8").gain(.2))
```

## Mixing

Target: integrated -18 to -12 LUFS, true peak under -1 dBFS. Ambient and intros may sit lower.
`.gain()` is linear and voices add up. Stay at .6 or lower per sound, but do not go timid: all tracks at .2 end near -30 LUFS.
Solo levels at gain .5: one saw or sine line -22 LUFS, kick bd -20, cp -23, `hh` only -39, gtr -16, `moog` -5 and clipping, bass1 -12, linnhats -24.
Starting gains: kick .5-.6; snare or clap .4-.5; `hh` .3-.5; linnhats, 808oh, cr .1-.25; synth bass .4-.6; moog and bass1 .2-.3; lead .3-.45; chords .2-.3 per voice, lower when doubled (.12-.15 with octaves plus superimpose).

Bands: sub and bass carry weight, mid carries the music, high and air carry presence. For most music aim for mid the largest share, high and air together at least 5%.

| Measurement | Code change |
| --- | --- |
| below -20 LUFS | raise gain of main parts toward .6; replace sine with sawtooth or triangle; add a mid layer; open lpf |
| above -10 LUFS or peak over -1 or clipping | lower the loudest low parts first; lower kick and bass by .05-.1 |
| sub plus bass over 70% | `.hpf(150)` on pads and chords; lower bass gain; raise lead |
| high under 3% | open lpf to 3000+, add `s("linnhats*8").gain(.15)` or `s("white*16").decay(.03).sustain(0).gain(.2)` |
| air over 25% or harsh | `.lpf(5000)`, lower hats |
| mid crowded | `.hpf(300)` on chords, move a part up an octave, use different rhythms |
| kick lost under bass | `.orbit(1).duck(2).duckdepth(.7)` on kick, `.orbit(2)` on bass |
| flat dynamics, little change over time | add `.mask`, `<>` sections, and a rise in `.lpf` |
| few attacks, no rhythm | `.struct`, staccato envelopes, percussion layer |
| peak fine but quiet parts vanish | lower the loudest track instead of raising all |

## Common failures

- Only sine pads: quiet, dull, nothing moves. Use several timbres with attacks.
- All tracks gain .2 or below: the mix ends near -30 LUFS.
- Chords at gain .6: each voice adds, and it clips.
- Same rhythm in every part, or every note the same length.
- Static loop: without `<>`, `every` or `mask`, no change happens after 4 beats.
- Mismatched keys: melody and chords must share one key.
- `let`, `const`, `$:`, `setcpm`, or more than one statement in a track.
