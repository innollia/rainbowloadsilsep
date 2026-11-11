# Akkado (nkido) authoring guide for game audio

You write Akkado source that is rendered offline to WAV. Targets: (a) short one-shot sound effects, (b) seamless ambience loops, (c) short music loops. Everything is synthesized from oscillators and noise. Output only constructs shown in this guide.

## Do NOT use

- `samples(...)`, sample patterns `s"..."`, `sample(...)`, `sample_loop(...)`, `.bank(...)`, `.variant(...)`
- `soundfont(...)`, `sf_voice(...)`, `$soundfont_alias(...)`, any `$directive`
- `wt_load(...)`, `smooch(...)`, `wt(...)`, `wavetable(...)`
- `in(...)` (audio input), `midi(...)`, `midi_cc(...)`
- `import`, file paths, URLs, `file://`, `http(s)://`, `github:`, `bundled://` anywhere in the source
- `pianoroll`, `oscilloscope`, `waveform`, `spectrum`, `waterfall`, `param`, `button`, `toggle`, `dropdown`
- Drum or sample names (`bd`, `sd`, `hh`, ...) in any pattern. Inside `n"..."` write only note names and `~`; any other word is treated as a sample name. Drums are synthesized (see examples).

## Program skeleton

A program is a list of statements. Audio is produced only by statements that end in `out(...)` or `bus(...)`; all such statements are summed.

```akkado
// render: 1 s
bpm = 120                                    // tempo; default 120. 1 beat = 1 cycle
master((s) -> limiter(s, -1.5, 0.1))         // clean master, hard ceiling at -1.5 dBFS
tone = sine(440) * 0.3                       // name = expression (names are immutable)
tone |> lp(@, 2000) |> out(@)                // out(sig): mono signal to both speakers
```

## Syntax essentials

- Comments: `// ...` only. Numbers: `440`, `0.5`, `1e3`. Operators: `+ - * /`, comparisons `> < >= <= ==` (yield 1 or 0), `&&`, `||`, `!`.
- `a |> f(@)` pipes `a` into the hole `@` of the next stage. `%` is an identical alias of `@`. `|>` binds looser than arithmetic, so `x |> lp(@, 800) * env |> out(@)` multiplies the filtered signal by `env`.
- A hole may be used several times in one stage: `x |> @ * 0.7 + saturate(@, 4) * 0.3`.
- Variables: `name = expr`. A name can be bound once; variables and functions share one namespace.
- Functions: `fn name(a, b = default) -> expr` or `-> { statements; last expression is the result }`.
- Named arguments: `lp(x, 800, q: 4)`. Positional arguments cannot be skipped; to reach a later one, pass the earlier ones or name it.
- Closures `(s) -> expr` are needed only for `master(...)` and `mixer(...)`.

```akkado
// render: 2 s
master((s) -> limiter(s, -1.5, 0.1))
fn pluck(freq, t, dec = 0.2) -> saw(freq) * ar(t, 0.001, dec) |> lp(@, 2500)
fn thick(freq) -> {
    a = saw(freq)
    b = saw(freq * 1.007)
    (a + b) * 0.5
}
pulse = trigger(1)                             // one pulse per beat
pluck(220, pulse, dec: 0.3) * 0.25 |> out(@)
thick(110) * ar(pulse, 0.005, 0.2) * 0.2
    |> lp(%, 900, q: 3)
    |> @ * 0.8 + saturate(@, 4) * 0.1
    |> out(@)
```

## Core functions

Frequencies in Hz, times in seconds unless noted. `sig` arguments accept numbers or signals (audio-rate modulation is fine). Effects take optional trailing `dry:` / `wet:` named arguments.

| Call | Meaning |
|---|---|
| `sine(freq)`, `tri(freq)`, `saw(freq)`, `sqr(freq)` | Oscillators, output -1..1. `sine(freq, 0, trig)` restarts phase at each trigger (tight kicks). |
| `phasor(freq)` | Ramp 0..1, `freq` times per second. `phasor(1 / T)` = normalized position inside a T-second loop. |
| `noise()` | White noise -1..1. `noise(0, 0, seed)` = independent stream per integer seed. |
| `lp(in, cut, q)`, `hp(in, cut, q)`, `bp(in, cut, q)` | Low/high/band-pass. `q` default 0.707, range 0.5..20. |
| `moog(in, cut, res)` | 4-pole ladder low-pass. `res` 0..4 (default 1, self-oscillates near 4). |
| `ar(trig, attack, release)` | One-shot envelope 0..1, fired by a trigger pulse. Defaults 0.01, 0.3. Release is exponential: about -60 dB after 1.5 x release. |
| `adsr(gate, attack, decay, sustain, release)` | Held envelope; `sustain` is a level 0..1. Use with a pattern's `.gate`. |
| `trigger(n)` | Pulse train, `n` pulses per beat (`trigger(4)` = 16ths, `trigger(0.25)` = every 4 beats). First pulse at time 0. |
| `delay(in, time, fb)` | Echo. `time` 0..10 s, `fb` 0..1. Defaults `dry: 1, wet: 0.5`. |
| `freeverb(in, room, damp)` | Reverb, stereo out. `room` 0..1, `damp` 0..1. Defaults `dry: 1, wet: 0.5`. |
| `saturate(in, drive)` | tanh distortion, `drive` 1..10 (default 2). |
| `softclip(in, thresh)` | Soft clipper, `thresh` 0..1 (default 0.5). |
| `bitcrush(in, bits, rate)` | `bits` 1..16 (default 8), `rate` 0..1 sample-rate reduction (default 0.5). |
| `limiter(in, ceiling, release)` | `ceiling` in dB (e.g. -1.5), `release` in seconds (0.1). |
| `comp(in, thresh, ratio)` | Compressor. `thresh` in dB (default -12), `ratio` (default 4). |
| `pan(sig, pos)` | Equal-power pan, `pos` -1 (left) .. +1 (right). Mono in, stereo out. |
| `stereo(L, R)`, `left(s)`, `right(s)` | Build / split a stereo signal. |
| `out(L)` / `out(L, R)` | Send to the master (bus 0). |
| `bus(N, sig, "label")`, `mixer(N, (s) -> ..., "label")`, `master((s) -> ...)` | Stem routing and per-bus processing (see Stems). |
| `mtof(note)` | MIDI note number to Hz (69 -> 440). |
| `select(cond, a, b)` | `a` where `cond > 0`, else `b`. There is no `?:`. |
| `sah(in, trig)` | Sample-and-hold `in` at each trigger (random steps from noise). |
| `gateup(sig)` | 1-sample pulse when `sig` rises above 0; turns a comparison into a trigger. |
| `clamp(x, lo, hi)`, `abs`, `min(a, b)`, `max(a, b)`, `pow(a, b)`, `exp`, `sin`, `cos` | Math. `sin(x)` / `cos(x)` take radians and are NOT oscillators. |
| `bpm`, `spb` | Tempo; `spb` = seconds per beat (read-only), e.g. `delay(x, spb * 0.5, 0.4)`. |

```akkado
// render: 2 s
master((s) -> limiter(s, -1.5, 0.1))
t = trigger(0.5)
src = sqr(mtof(57)) * ar(t, 0.002, 0.2) * 0.5            // mtof(57) = 220 Hz
src |> moog(@, 300 + ar(t, 0.01, 0.3) * 2500, 2.5)       // envelope opens the filter
    |> bitcrush(@, 6, 0.4)
    |> softclip(@, 0.8)
    |> delay(@, spb * 0.5, 0.4, wet: 0.35)
    |> freeverb(@, 0.6, 0.5, wet: 0.25)
    |> out(@)
```

## One-shot sound effects

Rendering always starts at time 0 and `trigger(n)` fires its first pulse at sample 0. `trigger(0.001)` fires once at the start and not again for 1000 beats: use it as the single hit of a sound effect. Drive every envelope (amplitude, pitch, filter) from that one trigger. The sound must decay to silence before the render ends: render length >= attack + 1.5 x longest release + any delay/reverb tail.

```akkado
// render: 0.5 s
master((s) -> limiter(s, -1.5, 0.1))
hit = trigger(0.001)                                     // exactly one pulse, at time 0
sine(500 + ar(hit, 0.001, 0.05) * 900, 0, hit)           // pitch envelope
    |> @ * ar(hit, 0.002, 0.2) * 0.5                     // amplitude envelope
    |> out(@)
```

For a one-shot with several notes, use a pattern whose cycle is longer than the render and pad it with rests (see the coin example).

## Sequencing with mini-notation

Pattern literals: `n"..."` notes (`c4`, `f#3`, `a#1`, `bb2`; converted to Hz) and `v"..."` plain numbers. Bind a pattern with `as` at the head of a pipeline and read its fields:

- `e.freq` Hz, `e.vel` velocity 0..1 (default 1)
- `e.trig` one-sample pulse at each note start (use with `ar`)
- `e.gate` high for the note's duration (use with `adsr`)

Timing rules (these differ from Strudel/Tidal):

- **Each top-level element lasts one beat.** `n"c4 e4 g4 c5"` is 4 beats long, then repeats.
- `[a b c]` subdivides its slot: `n"[c4 e4] g4"` = two 8th notes, then a quarter.
- `~` is a rest. `a*3` repeats inside the slot (`1*2` = two 8ths). `a!3` = `a a a` (three slots).
- `<a b>` plays one alternative per pass. `.slow(k)` / `.fast(k)` after the literal stretch/compress time (`n"a3 f3".slow(4)` = 4 beats per note).
- Patterns of different lengths loop independently: `v"1"` (every beat), `v"~ 1"` (beats 2 and 4), `v"[~ 1]"` (off-beat 8ths).
- A pattern used directly as a number steps through its values: `lp(x, v"400 800 1600 800")`.

```akkado
// render: 4 s
bpm = 120
master((s) -> limiter(s, -1.5, 0.1))
n"c4 [e4 g4] ~ <c5 b4>" as e                             // 4 beats; slot 4 alternates each pass
    |> tri(e.freq) * adsr(e.gate, 0.005, 0.08, 0.5, 0.05) * e.vel * 0.25
    |> out(@)
v"1 ~ 1*2 [~ 1]" as k                                    // rhythm only: values unused, .trig drives the drum
    |> sine(60, 0, k.trig) * ar(k.trig, 0.001, 0.15) * 0.35
    |> out(@)
n"c2!2 g1!2".slow(2) as d                                // each note lasts 2 beats
    |> saw(d.freq) * ar(d.trig, 0.01, 0.5) * 0.15
    |> lp(@, v"300 600 1200 600")                        // cutoff steps once per beat
    |> out(@)
```

## Tempo and time

- `bpm = N` once at the top (constant only). Beat length = `60 / bpm` seconds.
- Seconds for B beats: `B * 60 / bpm`. 8 beats at 120 BPM = 4 s; 16 beats at 100 BPM = 9.6 s.
- Sample rate is 48000 Hz. Free-running LFOs are in Hz, not beats: use `sine(hz)` as an LFO (-1..1).

## Stereo

Mono signals widen automatically; effects process both channels. Create width with `pan`, `out(L, R)`, or `stereo(L, R)`. Two identical calls such as `noise()` and `noise()` produce the same samples (zero width): give noise different seeds, or detune oscillators.

```akkado
// render: 2 s
master((s) -> limiter(s, -1.5, 0.1))
t = trigger(2)
blip = sine(660) * ar(t, 0.002, 0.1) * 0.4
air = stereo(noise(0, 0, 1), noise(0, 0, 2)) |> hp(@, 6000) |> @ * 0.05
blip |> pan(@, sine(0.5) * 0.8) |> out(@)                // auto-pan
air |> out(@)
out(saw(110) * 0.08, saw(111) * 0.08)                    // explicit left, right
```

## Stems: buses with labels

Route each instrument group to its own numbered bus with a label: `sig |> bus(N, @, "label")`. N is an integer literal 1..199. Several statements may write to the same bus (they sum); give them the same label. Every bus is automatically mixed into the master, so do not also send the same signal to `out`. The renderer writes the full mix plus one WAV per bus named after its label. Labels: lowercase letters, digits, `-` only. Anything sent straight to `out(...)` is in the mix but in no stem, so in stem-separated music route everything through labeled buses. `mixer(N, (s) -> ..., "label")` optionally processes a whole bus.

```akkado
// render: 2 s
bpm = 120
master((s) -> limiter(s, -1.5, 0.1))
v"1" as k |> sine(55, 0, k.trig) * ar(k.trig, 0.001, 0.2) * 0.4 |> bus(1, @, "drums")
v"[~ 1]" as h |> noise() * ar(h.trig, 0.001, 0.03) * 0.12 |> hp(@, 7000) |> bus(1, @, "drums")
n"c2 c2 g1 [a#1 ~]" as b
    |> saw(b.freq) * adsr(b.gate, 0.005, 0.1, 0.6, 0.05) * 0.22
    |> lp(@, 700)
    |> bus(2, @, "bass")
mixer(2, (s) -> s |> saturate(@, 2) |> @ * 0.8, "bass")  // optional per-bus FX
```

## Loudness

- Always start with `master((s) -> limiter(s, -1.5, 0.1))`. Without a `master(...)` line the engine applies a soft-clipper that colors everything and lets peaks reach -0.9 dBFS.
- The limiter is a safety net, not the mix. Scale sources so the sum stays below about 0.7: oscillators are full scale (+-1), so multiply every voice by a gain. Typical gains: single SFX voice 0.3..0.6; in music kick 0.35, snare 0.2, hats 0.1, bass 0.2..0.25, lead 0.15, pad 0.08.
- Stems are captured before the master limiter. Each bus must itself stay below 0.89 (-1 dBFS) or its stem clips. If unsure add `mixer(N, (s) -> limiter(s, -3, 0.1), "label")`.
- Resonant filters (`q` > 4, `moog` res > 3), `saturate`, feedback delays and summed detuned oscillators raise level: lower the gain after them.
- Give every envelope an attack >= 0.001 s. `tri` starts at +1 and `saw` at -1, so an un-enveloped start clicks.

## Seamless loops

- Choose the loop length in beats, then render exactly `beats * 60 / bpm` seconds. Use a length whose seconds x 375 is an integer (the renderer works in 128-sample blocks). Safe tempos for 4-beat multiples: 60, 75, 80, 90, 96, 100, 120, 125, 144, 150, 160, 180.
- Every pattern length must divide the loop length (a 3-beat pattern does not loop inside 8 beats).
- Every voice must be silent at the loop point: use decaying `ar` envelopes that finish before the end, and when using `adsr` with `.gate`, end the pattern with a rest (`[g1 ~]`) so the last note has released.
- Delay and reverb tails are cut at the end and missing at the start. In loops keep them off, or short and quiet (`wet` <= 0.2).
- Free-running modulation must repeat with the loop: derive it from `ph = phasor(1 / loop_seconds)` (e.g. `cos(ph * 6.28318)`), or use `sine(k / loop_seconds)` with integer k.
- Sustained un-enveloped tones (drones) need `freq * loop_seconds` to be an integer.
- Noise beds cannot be periodic; keep their level and filter modulation periodic and make the modulation quietest at the loop point.

## Common mistakes

- **Reusing a taken name.** A name can be bound only once, and builtin/library names cannot be variables. These fail with `E150`: `drop`, `snap`, `gate`, `room`, `pan`, `key`, `scale`, `dur`, `voice`, `mode`, `bend`, `swing`, `run`, `rev`, `fast`, `slow`, `sum`, `min`, `max`, `sub`, `fold`, `tube`, `lfo`, `osc`, `beat`, `chord`, plus every function in this guide (`noise`, `delay`, `out`, ...). Safe names: `hit`, `env`, `kick`, `snare`, `hat`, `bass`, `lead`, `pad`, `tone`, `body`, `tail`, `sweep`, `fall`, `rise`.
- **Reading pattern fields from a plain variable.** `k = v"1 ~"` followed by `k.trig` compiles but is silent or drops notes. Always bind with `as` in the pipeline head: `v"1 ~" as k |> ... k.trig ...`.
- **Assuming Strudel timing.** `n"c4 e4 g4 c5"` takes four beats, not one. Wrap in `[...]` to fit one beat.
- **Putting modifiers outside the string.** `n"c4 e4"/2` divides the signal by 2. Write `n"[c4 e4]/2"` or `.slow(2)`.
- **`sin` vs `sine`.** `sin(440)` is the math function (a constant). The oscillator is `sine(440)`.
- **Skipping arguments by name.** `noise(seed: 2)` is an error; write `noise(0, 0, 2)`.
- **Expecting two `noise()` calls to differ.** They are identical; use seeds for stereo or layered noise.
- **Piping inside a call argument.** `out(a, b |> lp(@, 900))` mis-parses. Bind first: `r = b |> lp(@, 900)` then `out(a, r)`.
- **Using a second trigger for a later event in a one-shot.** `trigger` is periodic. For a delayed second event use a padded pattern (`n"[b5 e6 ~ ~] ~ ~ ~"`), not another `trigger`.
- **Render shorter than the tail.** `ar(hit, 0.001, 0.6)` needs about 0.9 s to reach silence; a one-shot file must end in silence.
- **A held note across the loop point.** With `adsr(e.gate, ...)` a note filling the last beat is cut at full level and the loop clicks. End with a rest.
- **Sending the same signal to `bus` and `out`.** It is then doubled in the mix.
- **Non-literal bus index or missing label.** `bus(n, ...)` with a variable fails (`E260`); an unlabeled bus yields a stem named `busN`.
- **Calling functions not listed here.** `euclid`, `fold` (breaks a following `delay`), `lfo`, `beat`, `co`, `poly`, chord patterns and others are unreliable in this setup or forbidden; build from the listed primitives and write rhythms as patterns.
- **Hot levels.** Three full-scale oscillators summed = 3.0. Multiply each voice by its gain before summing.

## Examples

Each example is a complete program. The comment on the first line gives the render length.

### UI click

```akkado
// UI click. render: 0.2 s
master((s) -> limiter(s, -1.5, 0.1))
hit = trigger(0.001)
tick = sine(1800 + ar(hit, 0.0005, 0.01) * 1200, 0, hit) * ar(hit, 0.0005, 0.03)
zap = noise() |> hp(@, 5000) |> @ * ar(hit, 0.0005, 0.008)
tick * 0.5 + zap * 0.25 |> out(@)
```

### Jump

```akkado
// Jump. render: 0.4 s
master((s) -> limiter(s, -1.5, 0.1))
hit = trigger(0.001)
rise = ar(hit, 0.14, 0.05)                 // 0 -> 1 over 0.14 s
sqr(220 + rise * 520) * ar(hit, 0.002, 0.16) * 0.35
    |> lp(@, 4000)
    |> out(@)
```

### Coin pickup

```akkado
// Coin pickup (two quick notes). render: 0.8 s
bpm = 120
master((s) -> limiter(s, -1.5, 0.1))
n"[b5 e6 ~ ~] ~ ~ ~ ~ ~ ~ ~" as e
    |> (sqr(e.freq) * 0.6 + tri(e.freq * 2) * 0.4) * ar(e.trig, 0.001, 0.22) * 0.35
    |> out(@)
```

### Explosion

```akkado
// Explosion. render: 1.5 s
master((s) -> limiter(s, -1.5, 0.1))
hit = trigger(0.001)
env = ar(hit, 0.002, 0.6)
crackle = stereo(noise(0, 0, 1), noise(0, 0, 2)) |> lp(@, 120 + env * 3500) |> @ * env
boom = sine(38 + ar(hit, 0.001, 0.12) * 90, 0, hit) * ar(hit, 0.002, 0.45)
crackle * 0.9 + boom * 0.9
    |> saturate(@, 3)
    |> @ * 0.6
    |> out(@)
```

### Laser shot

```akkado
// Laser shot. render: 0.5 s
master((s) -> limiter(s, -1.5, 0.1))
hit = trigger(0.001)
fall = ar(hit, 0.0005, 0.07)               // 1 -> 0 pitch fall
f = 280 + fall * 2200
(saw(f) + sqr(f * 1.01)) * ar(hit, 0.001, 0.14) * 0.22
    |> lp(@, 5000, 2)
    |> pan(@, 0.2)
    |> out(@)
```

### Wind ambience loop

```akkado
// Wind ambience loop. render: 8 s (loop = 8 s)
master((s) -> limiter(s, -1.5, 0.1))
ph = phasor(0.125)                                   // 0 -> 1 once per 8 s
gust = 0.5 - 0.3 * cos(ph * 6.28318) + 0.15 * sin(ph * 18.84954)   // periodic, quietest at the seam
wl = noise(0, 0, 1) |> bp(@, 350 + gust * 550, 1.5)
wr = noise(0, 0, 2) |> bp(@, 400 + gust * 550, 1.5)
stereo(wl, wr) * (0.15 + gust * 0.6) |> out(@)
```

### Rain ambience loop

```akkado
// Rain ambience loop. render: 4 s (loop = 4 s)
master((s) -> limiter(s, -1.5, 0.1))
hiss = stereo(noise(0, 0, 1), noise(0, 0, 2)) |> hp(@, 2500) |> lp(@, 9000)
dl = (noise(0, 0, 3) > 0.9994) |> bp(@, 2800, 6)        // sparse random drops
dr = (noise(0, 0, 4) > 0.9994) |> bp(@, 3600, 6)
swell = 0.85 + 0.15 * sine(0.25)                        // 1/4 Hz repeats every 4 s
hiss * 0.25 * swell + stereo(dl, dr) * 0.5 |> out(@)
```

### Music loop A (3 stems: drums, bass, lead)

```akkado
// Music loop: drums + bass + lead. 8 beats at 120 BPM. render: 4 s (loop = 4 s)
bpm = 120
master((s) -> limiter(s, -1.5, 0.1))

fn kick(t) -> sine(45 + ar(t, 0.001, 0.04) * 150, 0, t) * ar(t, 0.001, 0.2)
fn snare(t) -> {
    body = tri(190) * ar(t, 0.001, 0.06)
    rattle = noise() |> bp(@, 1800, 1.2) |> @ * ar(t, 0.001, 0.12)
    body * 0.5 + rattle
}
fn hat(t) -> noise(0, 0, 5) |> hp(@, 7000) |> @ * ar(t, 0.001, 0.035)

// drums -> bus 1 (several writers sum into the same bus)
v"1" as k |> kick(k.trig) * 0.34 |> bus(1, @, "drums")
v"~ 1" as s |> snare(s.trig) * 0.2 |> bus(1, @, "drums")
v"[~ 1]" as h |> hat(h.trig) * 0.1 |> pan(@, 0.3) |> bus(1, @, "drums")

// bass -> bus 2 (last note is shortened so it has released before the loop point)
n"c2 c2 [c2 c3] c2 f1 f1 [f1 f2] [g1 ~]" as b
    |> saw(b.freq)
    |> lp(@, 300 + ar(b.trig, 0.005, 0.15) * 900, 2)
    |> @ * adsr(b.gate, 0.005, 0.1, 0.7, 0.05) * 0.2
    |> bus(2, @, "bass")

// lead -> bus 3
n"[c5 e5] [g5 e5] [c5 ~] g4 [a4 c5] [f5 c5] [e5 d5] ~" as m
    |> sqr(m.freq) * ar(m.trig, 0.003, 0.16) * 0.16
    |> lp(@, 3500)
    |> pan(@, -0.25)
    |> bus(3, @, "lead")
```

### Music loop B (4 stems: drums, bass, pad, arp)

```akkado
// Music loop: drums + bass + pad + arp. 16 beats at 100 BPM. render: 9.6 s (loop = 9.6 s)
bpm = 100
master((s) -> limiter(s, -1.5, 0.1))

fn kick(t) -> sine(45 + ar(t, 0.001, 0.04) * 150, 0, t) * ar(t, 0.001, 0.18)
fn hat(t) -> noise() |> hp(@, 8000) |> @ * ar(t, 0.001, 0.03)

v"1 ~ 1 [~ 1]" as k |> kick(k.trig) * 0.42 |> bus(1, @, "drums")
v"[1 1] [1 1 1 1]" as h |> hat(h.trig) * 0.08 |> bus(1, @, "drums")
mixer(1, (s) -> limiter(s, -3, 0.1), "drums")        // optional per-stem safety limiter

// one root per 4 beats (Am F C G), plucked on every beat
n"a1!4 f1!4 c2!4 g1!4" as b
    |> (tri(b.freq) + sine(b.freq * 2) * 0.3) * ar(b.trig, 0.005, 0.25) * 0.26
    |> bus(2, @, "bass")

// pad: one swell per chord; AR finishes before the next chord and before the loop point
n"a3 f3 c4 g3".slow(4) as p
    |> saw(p.freq) + saw(p.freq * 1.503) + saw(p.freq * 2.005)
    |> lp(@, 1200)
    |> @ * ar(p.trig, 0.6, 0.8) * 0.08
    |> bus(3, @, "pad")

n"[a4 c5 e5 c5] [a4 c5 e5 a5] [e5 c5 a4 c5] [e5 a5 e5 c5] [f4 a4 c5 a4] [f4 a4 c5 f5] [c5 a4 f4 a4] [c5 f5 c5 a4] [c5 e5 g5 e5] [c5 e5 g5 c6] [g5 e5 c5 e5] [g5 c6 g5 e5] [g4 b4 d5 b4] [g4 b4 d5 g5] [d5 b4 g4 b4] [d5 g5 d5 b4]" as a
    |> sine(a.freq) * ar(a.trig, 0.002, 0.1) * 0.13
    |> pan(@, 0.35)
    |> bus(4, @, "arp")
```
