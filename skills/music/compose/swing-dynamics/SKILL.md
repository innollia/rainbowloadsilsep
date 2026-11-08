---
name: Swing and dynamics
description: 스윙 위치와 % 값, 셈여림(벨로시티) 위계, 고스트노트, 미세 타이밍과 휴머나이즈
keywords: 스윙, 셔플, 셈여림, 세기, 벨로시티, 고스트, 강약, 사람 같, 기계 같, 로봇, 뻣뻣, 끈적, 늘어지, swing, shuffle, velocity, dynamics, ghost note, humanize, robotic, mechanical, laid back, feel
---

Velocity:
- Velocity asymmetry is the single biggest lever. A flat-velocity pattern sounds mechanical even with perfect timing. Hierarchy: kick/snare accents 80-100%, regular hats 50-70%, ghost notes 20-40%, off-beat accents 60-75%.
- `.gain("...")` is the velocity sequencer: `s("hh*8").gain(".3 .3 1 .3 .3 1 .3 1")`. Even three gain values (loud / mid / quiet) are transformative. Small variation (10-15%) already removes the machine-gun effect.
- Syncopate with dynamics instead of timing: keep the melody on the grid, raise off-beat gain, soften on-beats.
- Delete the hat note that coincides with the snare so the snare speaks.

Ghost notes:
- A very quiet hit on a "wrong" beat, typically a snare ghost on the 16th before a backbeat: `s("~ [sd sd] ~ sd").gain("1 [.3 1] 1 1")`. One or two per bar is enough; more becomes clutter.
- A ghost at 80% is just a hit in the wrong place; 25-35% is the useful range. Keep ghosts very short.

Swing:
- Swing delays the second note of each pair. 50% = straight, 66% = triplet swing (jazz hats, shuffle), 75% = dotted. House and hip-hop sweet spot 54-62%; heavier boom-bap and 90s MPC feel 58-65%; funk drums about 54-56%; jazz 8ths about 70%. Below 50% is reverse swing: rushed, urgent, galloping, awkward.
- In this engine `.swingBy(x, n)`: x = 2 × swing − 1 (54% → .08, 58% → .16, 62% → .24, 66% → 1/3); n = 4 swings 8ths, n = 8 swings 16ths. `.swing(n)` is `swingBy(1/3, n)`.
- Don't apply swing globally: swing the hats and snare, leave the kick and bass on the grid. A swung kick in 4/4 house sounds drunk. Exception: in hip-hop the whole kit swings together. Techno: minimal to none.
- Add swing gradually by ear; even a small amount (about 53%) makes a part come alive. Wrong swing for the style ruins it: a swung feel on an aggressive straight track turns it into a jaunty knees-up.
- Change swing and syncopation separately; they are different controls. Set the tempo first: at the wrong bpm, 16th-note accents turn into mush.
`[hats] s("hh*16").gain(".35 .25 .7 .25").swingBy(.16,8)` with `[kick] s("bd*4")` straight.

Timing:
- Slight lateness = relaxed, early = urgent. `.late()` and `.early()` are in cycles: at 120 bpm `.late(.005)` is about 10 ms. Pull the snare 10-15 ms late for pocket: `s("~ sd ~ sd").late(.006)`.
- Keep the kick (and usually the snare) tight to the grid; humanize the hats and percussion. Timing variation alone sounds sloppy; combine it with velocity variation: `s("hh*8").gain(".4 .6 1 .4 .5 1 .35 .9").sometimesBy(.15,x=>x.late(.004))`.
- Full quantization for techno and minimal; light humanization (5-10% gain spread, 1-2 ms nudges) for house and hip-hop; heavy, whole kit off-grid for boom-bap and jazz-influenced beats. Too much humanization sounds sloppy, not human.
- Break repetition: add an occasional note that appears nowhere else, or drop one, so the bar doesn't feel copy-pasted: `.sometimesBy(.1,x=>x.ply(2))`.
