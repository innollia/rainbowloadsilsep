---
name: Arrangement
description: 음역 나누기, 긴 곡 구성, 섹션 역할, 반복 변주, 훅 피로, 긴장과 해소, 빼기로 만드는 긴장, '더'를 요청받았을 때 층 쌓기
---

- Registers, each part with its own place: sub/bass (c1-c3), harmony (c3-c5), lead (c4-c6), air (hats, noise). Never stack two parts in the same octave at the same level.
- Long form: give each track `<>` with long patterns, `.slow(8)`, or `.mask("<0 0 1 1>/4")` so parts enter and leave.
- The peak only feels like one if something was genuinely quiet first. Pull intros and breakdowns down hard (cut voices, drop gains). Place the first big climax around 50-65% through; a second peak needs a different timbre or register, not just louder.
- Section roles: intro strips to 1-3 elements and never front-loads the best hook; build rises through addition and a moving filter; drop is full density with the hook; breakdown strips the drums, adds space, lets the melody be exposed; outro removes elements in reverse order of entry.
- Repetition without monotony: same chords with a new top voice; sustained → stabs → anticipated; bass root → inversions on the second pass; m7 → m9 as the track builds; the same progression an octave up on a different instrument; drop the bass, then bring it back.
- Hook fatigue: a great melodic idea becomes invisible after 4-6 loops. Re-timbrate, don't rewrite; automate the filter, not the notes; shift the octave on the 3rd or 4th statement; let the hook answer itself with `.off()`.
- Change something every 8 bars. It doesn't have to be dramatic: a new hi-hat pattern, a filter nudge, one layer in or out. After 32 bars of identical material, something must shift.
- Subtraction creates as much tension as addition. Strip the kick before the drop and the kick return IS the drop. Remove the bass during the breakdown and its return powers the re-build. One beat of silence before a drop is the cheapest high-impact move.
- Variation: `.every(4,fast(2))`, `.sometimes(x=>x.add(note(12)))`, `.lastOf(4,rev)`, `.degradeBy(.2)`, `.rarely(ply(2))`.
- Tension: rising filter `.lpf(saw.range(500,4000).slow(16))`, thinner bass, higher register, faster hats. Release: full stack on a downbeat, lower register, one bar of silence before it.
- Song sections in one track: `arrange([4,s("bd*2")],[4,s("bd*4,hh*8")])`.
- Every request for "more" means new layers with different rhythm and register, not longer held notes.
