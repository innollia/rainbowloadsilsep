---
name: Harmony and melody
description: 조성, 코드와 보이싱, 베이스 라인, 아르페지오, 진행, 멜로디와 대선율 쓰는 법
---

- Key: `n("0 2 4 7").scale("C:minor")`. Scale names: major minor dorian mixolydian lydian phrygian "minor:pentatonic" "major:pentatonic" blues. Scale degrees cannot go out of key, so prefer them for melodies.
- Chords: `chord("<Am7 F^7 C^7 G7>").voicing()` gives smooth voice leading. Symbols: `Am7 Dm9 G7 C^7 F^7 Bb^7 Asus4 Cadd9`.
- Bass from chords: `chord("<Am F C G>").rootNotes(2)`.
- Arpeggio: `chord("<Am F>").voicing().arp("0 1 2 1")`.
- Progressions: pop I-V-vi-IV; emotional vi-IV-I-V; jazz ii-V-I; epic minor i-VI-III-VII; dark i-iv-VI-V; lofi IVmaj7-iiim7-iim7-Imaj7.
- Bass moves on chord changes and stays out of the melody's rhythm. Melody uses chord tones on strong beats and steps between; leave rests. Answer a 2-bar phrase with a varied 2-bar phrase.
- Counterpoint: when melody rises let a second line fall; `.off(1/8,x=>x.add(note(12)))` gives an echo line; `.rev()` or a slower copy gives a counter-line.
