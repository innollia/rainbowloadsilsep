---
name: Mixing
description: 목표 음량, 트랙별 시작 gain, 대역 비율, 측정값별 코드 수정 표
---

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
