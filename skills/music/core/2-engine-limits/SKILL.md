---
name: Engine limits
description: 이 엔진에서 안 되는 함수와 대신 쓸 것
---

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
