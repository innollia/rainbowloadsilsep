"""The one measuring and linting module (measure.js) and its command line (tools/asset_lint.js): WAV reading, loudness, true peak, the rule table and the id rule."""
import base64, json, math, pathlib, struct, subprocess, wave

REPO = pathlib.Path(__file__).parents[1]
MEASURE = REPO / "studio_frontend" / "asset_studio" / "measure.js"
LINT = REPO / "tools" / "asset_lint.js"
FIELDS = {"peak", "loud", "seconds", "clips", "lead", "tail", "dc", "seam", "wrap", "dip", "low", "mid", "high", "bright", "rate", "channels", "bits", "sample_peak", "end"}
SILENT = {"peak": -120, "loud": -70, "seconds": 0, "clips": 0, "lead": 0, "tail": 0, "dc": 0, "seam": 0, "wrap": 0, "dip": 0, "low": 0, "mid": 0, "high": 0, "bright": 0,
          "rate": 48000, "channels": 1, "bits": None, "sample_peak": -120, "end": -120}
NKIDO = {"name": "nkido (Akkado, Cedar)", "license": "MIT", "holder": "Moritz Laass", "use": "Sound synthesis engine"}

HELPERS = """
const M = window.assetMeasure;
const sine = (rate, hz, seconds, amp = 1, phase = 0) => Float32Array.from({ length: Math.round(rate * seconds) }, (_, i) => amp * Math.sin(2 * Math.PI * hz * i / rate + phase));
const quiet = (rate, seconds) => new Float32Array(Math.round(rate * seconds));
const join = (...parts) => { const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0)); let at = 0; for (const p of parts) { out.set(p, at); at += p.length; } return out; };
const one = (chans, rate = 48000) => M.measure({ rate, chans: Array.isArray(chans) ? chans : [chans] });
const ids = (issues) => issues.map((x) => x.id);
// lint always judges the name and the license too. `sound` gives it a record with nothing wrong, so only the sound rules can speak.
const sound = (facts, m, opts) => M.lint({ id: 'sfx_ok', sources: [{ name: 'x' }], ...facts }, m, opts);
"""


def node(script):
    # stdin: Windows caps a command line at 32K. The timeout turns a pattern that never finishes into a failure.
    out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    return json.loads(out.stdout)


def run(body):
    """The module the way the browser loads it (window.assetMeasure), driven like tests/test_asset_import.py."""
    src = "globalThis.window = globalThis;\n" + MEASURE.read_text(encoding="utf-8") + HELPERS
    return node(src + "\n(async () => {\n" + body + "\n})().catch((e) => { console.error(e); process.exit(1); });")


def cli(*args, cwd=None):
    return subprocess.run(["node", str(LINT), *map(str, args)], capture_output=True, text=True, encoding="utf-8", cwd=cwd, timeout=60)


def tone(rate, hz, seconds, amp=0.5, fade=0.0):
    n, edge = round(rate * seconds), max(1, round(rate * fade))
    return [amp * math.sin(2 * math.pi * hz * i / rate) * (min(1.0, i / edge, (n - 1 - i) / edge) if fade else 1.0) for i in range(n)]


def write_wav(path, chans, rate=48000):
    """16-bit PCM written by Python's own wave module, so readWav is checked against another writer."""
    ints = [max(-32768, min(32767, round(c[i] * 32768))) for i in range(len(chans[0])) for c in chans]
    with wave.open(str(path), "wb") as w:
        w.setnchannels(len(chans)); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack("<%dh" % len(ints), *ints))
    return path


def chunk(name, body):
    return name + struct.pack("<I", len(body)) + body + (b"\0" if len(body) % 2 else b"")


def wav_bytes(rate, bits, chans, kind=1, extensible=False, before_data=b"", claim=None):
    """A WAV built by hand from raw sample values: kind 1 is integer PCM, 3 is float."""
    width = bits // 8
    pack = {(1, 8): lambda v: struct.pack("<B", v), (1, 16): lambda v: struct.pack("<h", v), (1, 24): lambda v: struct.pack("<i", v)[:3],
            (1, 32): lambda v: struct.pack("<i", v), (3, 32): lambda v: struct.pack("<f", v), (3, 64): lambda v: struct.pack("<d", v)}.get((kind, bits), lambda v: bytes([v]))
    data = b"".join(pack(c[i]) for i in range(len(chans[0])) for c in chans)
    fmt = struct.pack("<HHIIHH", 0xFFFE if extensible else kind, len(chans), rate, rate * width * len(chans), width * len(chans), bits)
    if extensible:
        fmt += struct.pack("<HHIH", 22, bits, 0, kind) + bytes.fromhex("000000001000800000aa00389b71")
    body = b"WAVE" + chunk(b"fmt ", fmt) + before_data + (chunk(b"data", data) if claim is None else b"data" + struct.pack("<I", claim) + data)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_full_scale_997_hz_mono_sine_reads_minus_3_lufs():
    got = run("console.log(JSON.stringify(one(sine(48000, 997, 5))));")
    assert set(got) == FIELDS
    assert abs(got["loud"] + 3.01) < 0.1
    assert abs(got["sample_peak"]) < 0.01 and -0.01 < got["peak"] < 0.1
    assert got["rate"] == 48000 and got["channels"] == 1 and got["bits"] is None and abs(got["seconds"] - 5) < 1e-9


def test_loudness_gates_out_silence_and_far_quieter_parts():
    got = run("""
    const loudPart = sine(48000, 997, 4), soft = sine(48000, 997, 8, 10 ** (-30 / 20));
    console.log(JSON.stringify({ soft: one(soft).loud, thenSoft: one(join(loudPart, soft)).loud, thenSilence: one(join(loudPart, quiet(48000, 8))).loud,
      short: one(sine(48000, 997, 0.2)).loud, silence: one(quiet(48000, 2)).loud }));""")
    assert abs(got["soft"] + 33.01) < 0.1
    # Ungated, four loud seconds in twelve would read near -7.8. The gates leave the loud part and the three blocks that straddle its end.
    assert abs(got["thenSoft"] + 3.18) < 0.1 and abs(got["thenSilence"] + 3.18) < 0.1
    assert abs(got["short"] + 3.01) < 0.2  # under 400 ms: the level of the whole sound
    assert got["silence"] == -70


def test_true_peak_of_quarter_rate_sine_at_45_degrees_is_3_db_over_sample_peak():
    got = run("""
    const m = one(sine(48000, 12000, 1, 1, Math.PI / 4)), cd = one(sine(44100, 11025, 1, 1, Math.PI / 4), 44100);
    let r = 7; const noise = Float32Array.from({ length: 20000 }, () => { r = (r * 16807) % 2147483647; return r / 1073741824 - 1; }), n = one(noise.map((v) => v * 0.5));
    console.log(JSON.stringify({ m, cd, lint: sound({ kind: 'sfx' }, m), noise: [n.peak, n.sample_peak] }));""")
    for m in (got["m"], got["cd"]):
        assert abs(m["sample_peak"] + 3.01) < 0.01  # every sample sits at 0.707
        assert abs(m["peak"] - m["sample_peak"] - 3.01) < 0.3
        assert m["clips"] == 0
    assert [(x["id"], x["level"], x["limit"]) for x in got["lint"]] == [("peak", "error", -1)] and got["lint"][0]["value"] == got["m"]["peak"]
    assert got["noise"][0] >= got["noise"][1]  # the samples are part of the oversampled signal


def test_clip_lead_tail_dc_seam_and_end():
    got = run("""
    const rate = 48000, body = sine(rate, 440, 0.5, 0.5);
    const padded = one(join(quiet(rate, 0.1), body, quiet(rate, 0.3)));
    const c = new Float32Array(1000), full = 32767 / 32768, under = 32766 / 32768;
    c[10] = 1; c[11] = full; c[500] = -1; c[501] = -full; c[600] = under; c[601] = -under;
    const left = new Float32Array(1000), right = new Float32Array(1000);
    left[10] = 1; right[10] = -1; right[20] = 1;
    const offset = (v) => Float32Array.from({ length: rate }, (_, i) => v + 0.1 * Math.sin(2 * Math.PI * 100 * i / rate));
    const whole = sine(rate, 100, 1, 0.5), cut = sine(rate, 100, 1.0025, 0.5);
    const faded = join(body, quiet(rate, 0.05)), gap = one(join(body, quiet(rate, 0.5), body));
    console.log(JSON.stringify({
      lead: padded.lead, tail: padded.tail, paddedSfx: ids(sound({ kind: 'sfx' }, padded)), paddedLoop: ids(sound({ kind: 'amb', loop: true }, padded)),
      wrap: padded.wrap, dip: gap.dip, gapLoop: ids(sound({ kind: 'amb', loop: true }, gap)), gapSong: ids(sound({ kind: 'music', loop: true }, gap, { loud: [-70, 0] })),
      clips: one(c).clips, clipsStereo: one([left, right]).clips, clipLint: ids(sound({ kind: 'sfx' }, one(c))),
      dc: one(offset(0.01)).dc, dcStereo: one([offset(0.001), offset(-0.02)]).dc, dcNone: one(offset(0)).dc, dcLint: ids(sound({ kind: 'amb', loop: true }, one(offset(0.01)))),
      seamWhole: one(whole).seam, seamCut: one(cut).seam, seamStereo: one([sine(rate, 200, 1.0025, 0.5), cut]).seam, seamLint: [whole, cut].map((x) => ids(sound({ kind: 'amb', loop: true }, one(x)))),
      endRinging: one(body).end, endFaded: one(faded).end, endStereo: one([faded, join(quiet(rate, 0.05), body)]).end,
    }));""")
    assert abs(got["lead"] - 100) < 0.1 and abs(got["tail"] - 300) < 0.1
    assert got["paddedSfx"] == ["lead", "tail"] and got["paddedLoop"] == ["wrap"]  # a loop is not judged on its silences but on what they do to the repeat
    assert got["wrap"] > 60 and got["dip"] > 60  # a silent quarter second against a sounding one
    assert got["gapLoop"] == ["steady"] and got["gapSong"] == []  # music may stop and start again, ambience may not
    assert got["clips"] == 4 and got["clipsStereo"] == 2  # frames, not samples: both channels clipping together is one
    assert got["clipLint"] == ["peak", "clip"]
    assert abs(got["dc"] - 0.01) < 1e-4 and abs(got["dcStereo"] - 0.02) < 1e-4 and got["dcNone"] < 1e-5
    assert got["dcLint"] == ["dc"]
    assert got["seamWhole"] < 1.5 and got["seamCut"] > 50 and got["seamStereo"] > 50
    assert got["seamLint"] == [[], ["seam"]]
    assert abs(got["endRinging"] + 9.03) < 0.05 and got["endFaded"] == -120 and abs(got["endStereo"] + 9.03) < 0.05


def test_no_samples_and_one_sample_give_the_fixed_silent_result():
    empty = base64.b64encode(wav_bytes(44100, 16, [[], []])).decode()
    got = run("""
    const wav = M.readWav(Buffer.from('""" + empty + """', 'base64'));
    const none = one(new Float32Array(0)), single = one(Float32Array.of(1));
    console.log(JSON.stringify({ none, single, noChannels: M.measure({ rate: 48000, chans: [] }), wav: M.measure(wav), frames: wav.chans.map((c) => c.length),
      lint: [none, single].map((m) => sound({ kind: 'sfx' }, m)) }));""")
    assert got["none"] == SILENT
    assert got["single"] == {**SILENT, "seconds": 1 / 48000}
    assert got["noChannels"] == {**SILENT, "channels": 0}
    assert got["frames"] == [0, 0] and got["wav"] == {**SILENT, "rate": 44100, "channels": 2, "bits": 16}
    assert got["lint"] == [[], []]


def test_44100_hz_and_stereo():
    got = run("""
    const r = 44100, t = sine(r, 997, 5);
    console.log(JSON.stringify({ mono: one(t, r), both: one([t, t], r), left: one([t, quiet(r, 5)], r), anti: one([t, t.map((v) => -v)], r),
      uneven: one([sine(r, 997, 1, 0.25), sine(r, 997, 1, 0.5)], r) }));""")
    mono, both, anti = got["mono"], got["both"], got["anti"]
    assert mono["rate"] == 44100 and mono["channels"] == 1 and abs(mono["loud"] + 3.01) < 0.1
    assert both["channels"] == 2 and abs(both["loud"]) < 0.1  # two channels carry twice the power
    assert abs(got["left"]["loud"] + 3.01) < 0.1
    assert [both[k] for k in ("low", "mid", "high", "bright")] == [mono[k] for k in ("low", "mid", "high", "bright")]
    # Channels cancel in the mono sum: the bands see nothing, the per-channel measures still see a full-scale sound.
    assert [anti[k] for k in ("low", "mid", "high", "bright")] == [0, 0, 0, 0] and abs(anti["loud"]) < 0.1 and abs(anti["sample_peak"]) < 0.01
    assert abs(got["uneven"]["sample_peak"] + 6.02) < 0.01 and abs(got["uneven"]["peak"] + 6.02) < 0.1


def test_readwav_reads_every_pcm_width_float_and_odd_headers():
    files = {
        "u8": wav_bytes(8000, 8, [[128, 192, 0, 255]]),
        "i16": wav_bytes(22050, 16, [[0, 16384, -32768, 32767]]),
        "i24": wav_bytes(48000, 24, [[0, 4194304, -8388608, 8388607]]),
        "i32": wav_bytes(96000, 32, [[0, 1073741824, -2147483648]]),
        "f32": wav_bytes(48000, 32, [[0.0, 0.5, -1.0, 0.25]], kind=3),
        "stereo": wav_bytes(44100, 16, [[0, 16384, -16384], [8192, -8192, 32767]]),
        "extensible": wav_bytes(48000, 24, [[4194304, -4194304], [0, 8388607]], extensible=True),
        "listFirst": wav_bytes(48000, 16, [[16384, -16384]], before_data=chunk(b"LIST", b"abc")),  # an odd-sized chunk and its pad byte before the data
        "streamed": wav_bytes(48000, 16, [[16384, -16384, 8192]], claim=0xFFFFFFFF),  # a piped encoder never went back to fill in the size
    }
    bad = {"short": b"RIFF", "notWav": b"RIFF\x04\x00\x00\x00AVI LIST", "mulaw": wav_bytes(8000, 8, [[1, 2]], kind=7), "noData": wav_bytes(48000, 16, [[1]])[:36]}
    b64 = lambda d: json.dumps({k: base64.b64encode(v).decode() for k, v in d.items()})
    got = run("const files = " + b64(files) + ", bad = " + b64(bad) + """;
    const out = {}, shape = (w) => ({ keys: Object.keys(w), rate: w.rate, bits: w.bits, chans: w.chans.map((c) => Array.from(c)), typed: w.chans.every((c) => c instanceof Float32Array) });
    for (const [k, v] of Object.entries(files)) out[k] = shape(M.readWav(Buffer.from(v, 'base64')));
    const buf = Buffer.from(files.stereo, 'base64'), copy = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.length);
    out.fromArrayBuffer = shape(M.readWav(copy)); out.fromView = shape(M.readWav(new DataView(copy)));
    out.rejected = Object.fromEntries(Object.entries(bad).map(([k, v]) => { try { M.readWav(Buffer.from(v, 'base64')); return [k, false]; } catch (e) { return [k, e instanceof Error]; } }));
    console.log(JSON.stringify(out));""")
    want = {
        "u8": (8000, 8, [[0, 0.5, -1, 127 / 128]]),
        "i16": (22050, 16, [[0, 0.5, -1, 32767 / 32768]]),
        "i24": (48000, 24, [[0, 0.5, -1, 8388607 / 8388608]]),
        "i32": (96000, 32, [[0, 0.5, -1]]),
        "f32": (48000, 32, [[0, 0.5, -1, 0.25]]),
        "stereo": (44100, 16, [[0, 0.5, -0.5], [0.25, -0.25, 32767 / 32768]]),
        "extensible": (48000, 24, [[0.5, -0.5], [0, 8388607 / 8388608]]),
        "listFirst": (48000, 16, [[0.5, -0.5]]),
        "streamed": (48000, 16, [[0.5, -0.5, 0.25]]),
    }
    for name, (rate, bits, chans) in want.items():
        assert got[name] == {"keys": ["rate", "bits", "chans"], "rate": rate, "bits": bits, "chans": chans, "typed": True}, name
    assert got["fromArrayBuffer"] == got["stereo"] and got["fromView"] == got["stereo"]
    assert got["rejected"] == {"short": True, "notWav": True, "mulaw": True, "noData": True}


def test_rule_table_limits_levels_and_what_each_rule_applies_to():
    got = run("""
    const ok = { peak: -1, clips: 0, loud: -18, seconds: 2, lead: 50, tail: 200, dc: 0.002, seam: 3, wrap: 3, dip: 12 };
    const over = { peak: -0.99, clips: 1, loud: -15.9, seconds: 2.01, lead: 50.1, tail: 200.1, dc: 0.0021, seam: 3.01, wrap: 3.01, dip: 12.01 };
    const kinds = { sfx: { kind: 'sfx', loop: false }, amb: { kind: 'amb', loop: true }, song: { kind: 'music', loop: true }, sting: { kind: 'music', loop: false } };
    const each = (m, opts) => Object.fromEntries(Object.entries(kinds).map(([k, f]) => [k, ids(sound(f, m, opts))]));
    const loudAt = (loud, opts) => sound(kinds.song, { ...ok, loud }, opts);
    console.log(JSON.stringify({
      table: M.RULES.map((r) => [r.id, r.level, r.limit ?? r.range]), profiles: M.PROFILES,
      atLimit: each(ok), over: each(over), quietSong: ids(loudAt(-20.1)),
      issue: loudAt(-21), mobile: loudAt(-21, { profile: 'mobile' }), console: [loudAt(-21, { profile: 'console' }), loudAt(-24, { profile: 'console' }), loudAt(-26.1, { profile: 'console' })],
      wide: [loudAt(-21, { profile: 'wide' }), loudAt(-13.9, { profile: 'wide' })], own: [loudAt(-21, { loud: [-30, -10], profile: 'mobile' }), loudAt(-9, { loud: [-30, -10] })],
      musicFlag: ids(sound({ music: true }, { ...ok, loud: -5 })),
      record: M.lint({ kind: 'sfx', id: 'heal_sfx', sources: [] }, ok), recordOk: M.lint({ kind: 'sfx', id: 'sfx_heal', sources: [""" + json.dumps(NKIDO) + """] }, ok),
      notGiven: M.lint({ kind: 'sfx' }, ok), noFacts: ids(M.lint(null, ok)), noId: ids(M.lint({ kind: 'sfx', id: undefined, sources: [{}] }, ok)),
      noSources: [undefined, null, 'nkido', {}].map((sources) => ids(M.lint({ kind: 'sfx', id: 'sfx_a', sources }, ok))),
      unchecked: [ids(M.lint({ kind: 'sfx', sources: [{}] }, ok, { idRule: { check: false } })), ids(M.lint({ kind: 'sfx', id: 'Any Name', sources: [{}] }, ok, { idRule: { check: false } }))],
    }));""")
    assert got["table"] == [["peak", "error", -1], ["clip", "error", 0], ["loud", "error", [-20, -16]], ["dur", "warn", 2], ["lead", "warn", 50], ["tail", "warn", 200],
                            ["dc", "warn", 0.002], ["seam", "warn", 3], ["wrap", "warn", 3], ["steady", "warn", 12], ["name", "error", None], ["lic", "error", 1]]
    assert got["profiles"] == [{"id": "mobile", "loud": [-20, -16]}, {"id": "console", "loud": [-26, -22]}, {"id": "wide", "loud": [-26, -14]}]
    assert got["atLimit"] == {"sfx": [], "amb": [], "song": [], "sting": []}  # a value on the limit passes
    assert got["over"] == {
        "sfx": ["peak", "clip", "dur", "lead", "tail", "dc"],
        "amb": ["peak", "clip", "dc", "seam", "wrap", "steady"],
        "song": ["peak", "clip", "loud", "dc", "seam"],
        "sting": ["peak", "clip", "loud", "lead", "tail", "dc"],
    }
    assert got["quietSong"] == ["loud"]
    assert got["issue"] == [{"id": "loud", "level": "error", "value": -21, "limit": [-20, -16]}] and got["mobile"] == got["issue"]
    assert [[x["limit"] for x in issues] for issues in got["console"]] == [[[-26, -22]], [], [[-26, -22]]]
    assert [[x["limit"] for x in issues] for issues in got["wide"]] == [[], [[-26, -14]]]
    assert [[x["limit"] for x in issues] for issues in got["own"]] == [[], [[-30, -10]]]
    assert got["musicFlag"] == ["loud"]
    assert got["record"] == [{"id": "name", "level": "error", "value": "heal_sfx", "limit": "{kind}_{name}"}, {"id": "lic", "level": "error", "value": 0, "limit": 1}]
    assert got["recordOk"] == []
    # name and lic apply to everything: a record that says nothing about its id or its sources fails both, it does not skip them.
    assert got["notGiven"] == [{"id": "name", "level": "error", "value": None, "limit": "{kind}_{name}"}, {"id": "lic", "level": "error", "value": 0, "limit": 1}]
    assert got["noFacts"] == ["name", "lic"] and got["noId"] == ["name"]
    assert got["noSources"] == [["lic"]] * 4
    assert got["unchecked"] == [["name"], []]  # with the check off an id is still needed


def test_a_missing_or_non_finite_measurement_is_an_issue_not_a_pass():
    got = run("""
    const ok = { peak: -1, clips: 0, loud: -18, seconds: 2, lead: 50, tail: 200, dc: 0.002, seam: 3, wrap: 3, dip: 12 };
    const song = { kind: 'music', loop: true }, amb = { kind: 'amb', loop: true }, sfx = { kind: 'sfx' };
    const wild = one(Float32Array.from({ length: 4800 }, (_, i) => (i === 2400 ? NaN : 0.1 * Math.sin(i / 20))));
    const burst = one(Float32Array.from({ length: 4800 }, (_, i) => (i === 2400 ? Infinity : 0.1 * Math.sin(i / 20))));
    console.log(JSON.stringify({
      none: sound(song, null), empty: ids(sound(song, {})), undef: ids(sound(amb, undefined)), sfx: ids(sound(sfx, null)), everything: ids(M.lint({ kind: 'music' }, null)),
      nan: sound(sfx, { ...ok, peak: NaN, clips: NaN, dc: NaN, seam: NaN }), noLoud: ids(sound(song, { ...ok, loud: undefined })), inf: sound(sfx, { ...ok, peak: Infinity }),
      text: ids(sound(sfx, { ...ok, lead: '10' })), stillOk: sound(amb, ok),
      wild: [wild.peak, ids(sound(sfx, wild)).slice(0, 1)], burst: [burst.peak, burst.clips, ids(sound(sfx, burst)).slice(0, 2)],
    }));""")
    assert got["none"] == [{"id": "peak", "level": "error", "value": None, "limit": -1}, {"id": "clip", "level": "error", "value": None, "limit": 0},
                           {"id": "loud", "level": "error", "value": None, "limit": [-20, -16]}, {"id": "dc", "level": "warn", "value": None, "limit": 0.002},
                           {"id": "seam", "level": "warn", "value": None, "limit": 3}]
    assert got["empty"] == ["peak", "clip", "loud", "dc", "seam"] and got["undef"] == ["peak", "clip", "dc", "seam", "wrap", "steady"]
    assert got["sfx"] == ["peak", "clip", "dur", "lead", "tail", "dc"]
    assert got["everything"] == ["peak", "clip", "loud", "lead", "tail", "dc", "name", "lic"]
    # Only the rules that apply speak: a NaN seam says nothing about a sound that does not loop.
    assert [(x["id"], x["level"], x["value"]) for x in got["nan"]] == [("peak", "error", None), ("clip", "error", None), ("dc", "warn", None)]
    assert got["noLoud"] == ["loud"] and [(x["id"], x["value"]) for x in got["inf"]] == [("peak", None)]
    assert got["text"] == ["lead"] and got["stillOk"] == []
    # measure does not hide a sample that is not a number: the peak comes back as no number, which lint reads as over.
    assert got["wild"] == [None, ["peak"]] and got["burst"] == [None, 1, ["peak", "clip"]]


def test_id_rule_default_group_part_separator_and_check_off():
    got = run("""
    const grouped = { pattern: '{kind}_{cat}_{name}', sep: '_', prefix: { sfx: 'sfx', amb: 'amb', music: 'mus' }, check: true }, cats = ['ui', 'bgm', 'Env Night'];
    const ok = (list, rule, catIds) => list.map((id) => M.idOk(id, rule, catIds));
    console.log(JSON.stringify({
      plain: ok(['sfx_hit', 'sfx_hit_2', 'bgm_main_theme', 'amb_wind', 'heal_sfx', 'SFX_hit', 'sfx__hit', 'sfx_', 'sfx-hit', '']),
      grouped: ok(['mus_bgm_title', 'sfx_ui_click_2', 'amb_env_night_rain', 'bgm_title', 'sfx_click', 'mus_title', 'sfx_combat_hit'], grouped, cats),
      off: ok(['Anything at all', 'x', '', null, undefined], { ...grouped, check: false }, cats),
      kebab: ok(['ui-big-click', 'ui-big-click-3', 'ui_big_click', 'combat-hit'], { pattern: '{cat}-{name}', sep: '-' }, ['ui']),
      partial: ok(['mus_title', 'bgm_title', 'sfx_hit'], { prefix: { music: 'mus' } }),
      rule: M.ID_RULE,
    }));""")
    assert got["plain"] == [True, True, True, True, False, False, False, False, False, False]
    assert got["grouped"] == [True, True, True, False, False, False, False]
    assert got["off"] == [True, True, False, False, False]  # with the check off only an empty id is wrong
    assert got["kebab"] == [True, True, False, False]
    assert got["partial"] == [True, False, True]  # what a spec leaves out stays as the default
    assert got["rule"] == {"pattern": "{kind}_{name}", "sep": "_", "prefix": {"sfx": "sfx", "amb": "amb", "music": "bgm"}, "check": True}


def test_one_file_serves_the_browser_global_and_node_require():
    got = run("console.log(JSON.stringify({ same: module.exports === window.assetMeasure, keys: Object.keys(window.assetMeasure) }));")
    assert got["same"] is True and {"readWav", "measure", "RULES", "PROFILES", "idOk", "lint"} <= set(got["keys"])
    plain = node("const M = require(" + json.dumps(str(MEASURE)) + "); console.log(JSON.stringify({ keys: Object.keys(M), leaked: typeof assetMeasure }));")
    assert plain["keys"] == got["keys"] and plain["leaked"] == "undefined"


def test_command_line_json_equals_the_module_on_the_same_bytes(tmp_path):
    rate = 44100
    left = [0.0] * 4410 + tone(rate, 330, 0.4, 0.9) + [0.0] * 13230
    right = [0.0] * 4410 + [max(-1.0, min(1.0, 1.4 * v)) + 0.01 for v in tone(rate, 331, 0.4, 0.9)] + [0.0] * 13230
    path = write_wav(tmp_path / "sfx_hit.wav", [left, right], rate)
    mod = run("const w = M.readWav(require('fs').readFileSync(" + json.dumps(str(path)) + """)), m = M.measure(w);
    console.log(JSON.stringify({ measure: m, sfx: sound({ kind: 'sfx', loop: false }, m, { loud: [-20, -16] }), music: sound({ kind: 'music', loop: true }, m, { profile: 'console' }) }));""")
    one = cli(path, "--json", "--kind", "sfx", "--loud", "-20,-16")
    out = json.loads(one.stdout)
    assert out["measure"] == mod["measure"] and out["issues"] == mod["sfx"]
    assert out["file"] == str(path) and out["kind"] == "sfx" and out["loop"] is False and "id" not in out
    assert (out["measure"]["rate"], out["measure"]["channels"], out["measure"]["bits"]) == (44100, 2, 16)
    assert [x["id"] for x in out["issues"]] == ["peak", "clip", "lead", "tail", "dc"] and one.returncode == 1
    assert abs(out["measure"]["lead"] - 100) < 0.1 and abs(out["measure"]["tail"] - 300) < 1 and out["measure"]["clips"] > 8 and out["measure"]["dc"] > 0.004
    two = cli(path, "--json", "--kind=music", "--loop", "--profile", "console")
    assert json.loads(two.stdout)["issues"] == mod["music"] and "loud" in [x["id"] for x in mod["music"]]
    assert json.loads(two.stdout)["measure"] == mod["measure"]


def test_command_line_exits_1_only_for_error_level_issues(tmp_path):
    clean = tone(48000, 440, 0.3, 0.5, fade=0.01)
    clipped = write_wav(tmp_path / "clipped.wav", [[max(-1.0, min(1.0, 3 * v)) for v in clean]])
    late = write_wav(tmp_path / "late.wav", [[0.0] * 4800 + clean])
    fine = write_wav(tmp_path / "fine.wav", [clean])
    (tmp_path / "notes.wav").write_text("not audio", encoding="utf-8")

    bad = cli(clipped)  # no options at all
    assert bad.returncode == 1 and "error peak" in bad.stdout and "error clip" in bad.stdout
    warned = cli(late)
    assert warned.returncode == 0 and "warn  lead" in warned.stdout and "error" not in warned.stdout
    good = cli(fine)
    assert good.returncode == 0 and "no issues" in good.stdout
    assert json.loads(cli(fine, "--json").stdout)["issues"] == []
    for args in ([tmp_path / "notes.wav"], [tmp_path / "missing.wav"], [fine, "--kind", "voice"], [fine, "--loud", "loud"], [fine, "--profile", "pc"], [fine, "--sources", "{"], [fine, "--nope"], [fine, late], []):
        failed = cli(*args)
        assert failed.returncode == 2 and failed.stdout == "" and failed.stderr.startswith("asset_lint: "), args


def test_command_line_kind_from_prefix_and_when_name_and_license_are_judged(tmp_path):
    soft = tone(48000, 440, 1, 0.01, fade=0.01)
    paths = {name: write_wav(tmp_path / name, [soft]) for name in ("bgm_theme.wav", "amb_wind.wav", "Bad Name.wav")}
    look = lambda name, *args: json.loads(cli(paths[name], "--json", *args).stdout)
    names = lambda out: [x["id"] for x in out["issues"]]

    song = look("bgm_theme.wav")
    assert song["kind"] == "music" and names(song) == ["loud"] and song["issues"][0]["limit"] == [-20, -16]
    assert look("bgm_theme.wav", "--profile", "console")["issues"][0]["limit"] == [-26, -22]
    assert names(look("bgm_theme.wav", "--loud", "-60,-30")) == [] and names(look("bgm_theme.wav", "--kind", "sfx")) == []
    assert look("amb_wind.wav")["kind"] == "amb" and look("amb_wind.wav")["loop"] is False and look("amb_wind.wav", "--loop")["loop"] is True
    assert look("Bad Name.wav")["kind"] == "sfx"

    # No --id and no --spec: the file name is not judged. No --sources: neither is the license.
    assert names(look("Bad Name.wav")) == []
    assert names(look("Bad Name.wav", "--id", "Bad Name")) == ["name"] and look("Bad Name.wav", "--id", "sfx_good")["id"] == "sfx_good"
    assert names(look("Bad Name.wav", "--id", "sfx_good")) == []
    assert names(look("Bad Name.wav", "--id", "bgm_good", "--loud", "-60,-30")) == [] and look("Bad Name.wav", "--id", "bgm_good")["kind"] == "music"
    unlicensed = cli(paths["amb_wind.wav"], "--json", "--sources", "[]")
    assert unlicensed.returncode == 1 and json.loads(unlicensed.stdout)["issues"] == [{"id": "lic", "level": "error", "value": 0, "limit": 1}]
    licensed = cli(paths["amb_wind.wav"], "--json", "--sources", json.dumps([NKIDO]))
    assert licensed.returncode == 0 and json.loads(licensed.stdout)["issues"] == []


def test_spec_id_rule_gives_the_name_verdict_idOk_gives(tmp_path):
    path = write_wav(tmp_path / "mus_bgm_title.wav", [tone(48000, 997, 1, 0.5, fade=0.01)])
    ids = ["mus_bgm_title", "mus_bgm_title_2", "amb_bgm_rain", "sfx_ui_click", "bgm_title", "sfx_click", "mus_title", "Mus_Bgm_Title", ""]
    expected = {True: [True, True, True, True, False, False, False, False, False], False: [True] * 8 + [False]}
    for check in (True, False):
        rule = {"pattern": "{kind}_{cat}_{name}", "sep": "_", "prefix": {"sfx": "sfx", "amb": "amb", "music": "mus"}, "check": check}
        spec = {"game": "Test", "platform": "console", "id_rule": rule,
                "categories": [{"id": "ui", "name": "UI", "kind": "sfx"}, {"id": "bgm", "name": "Music", "kind": "music"}],
                "assets": [{"id": "mus_bgm_title", "category": "bgm", "loop": True}, {"id": "sfx_ui_click", "category": "ui", "loop": False}]}
        spec_path = tmp_path / ("spec-%s.json" % check)
        spec_path.write_text(json.dumps(spec), encoding="utf-8" if check else "utf-8-sig")  # one of the two starts with a byte order mark
        module = run("console.log(JSON.stringify(" + json.dumps(ids) + ".map((id) => M.idOk(id, " + json.dumps(rule) + ", ['ui', 'bgm']))));")
        assert module == expected[check]
        for asset_id, ok in zip(ids, module):
            out = json.loads(cli(path, "--json", "--spec", spec_path, "--id", asset_id).stdout)
            assert ("name" not in [x["id"] for x in out["issues"]]) == ok, (check, asset_id)
            assert out["id"] == asset_id

        # Without --id the file name is the id, and its entry in the spec says it is looping music on a console.
        own = json.loads(cli(path, "--json", "--spec", spec_path).stdout)
        assert own["id"] == "mus_bgm_title" and own["kind"] == "music" and own["loop"] is True
        assert [(x["id"], x["limit"]) for x in own["issues"]] == [("loud", [-26, -22])]
        click = json.loads(cli(path, "--json", "--spec", spec_path, "--id", "sfx_ui_click").stdout)
        assert click["kind"] == "sfx" and click["loop"] is False


def test_spec_is_read_the_way_the_asset_room_opens_it(tmp_path):
    path = write_wav(tmp_path / "fine.wav", [tone(48000, 440, 0.3, 0.5, fade=0.01)])

    def look(spec, asset_id):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(spec), encoding="utf-8")
        out = json.loads(cli(path, "--json", "--spec", spec_path, "--id", asset_id).stdout)
        return out["kind"], [x["id"] for x in out["issues"]]

    # An id rule without a pattern is not applied at all: the default rule, with its check on, judges.
    assert look({"id_rule": {"check": False}}, "Bad Name") == ("sfx", ["name"])
    assert look({"id_rule": {"pattern": "", "check": False}}, "Bad Name") == ("sfx", ["name"])
    assert look({"id_rule": {"prefix": {"sfx": "fx"}}}, "fx_hit") == ("sfx", ["name"])
    assert look({"id_rule": {"prefix": {"sfx": "fx"}}}, "sfx_hit") == ("sfx", [])
    assert look({"id_rule": {"pattern": "{kind}_{name}", "prefix": {"sfx": "fx"}}}, "fx_hit") == ("sfx", [])  # with a pattern the rest of the rule counts
    # A group whose kind is not one of the three holds effects, whatever the prefix of the id says.
    voice = {"categories": [{"id": "vo", "kind": "voice"}, {"id": "bgm", "kind": "music"}], "assets": [{"id": "bgm_vo_line", "category": "vo"}, {"id": "bgm_title", "category": "bgm"}]}
    assert look(voice, "bgm_vo_line") == ("sfx", [])
    assert look(voice, "bgm_title") == ("music", ["loud"])
    assert look(voice, "bgm_other")[0] == "music"  # not in the spec, so the prefix says


def test_readwav_refuses_what_it_would_misread_and_reads_a_stream_with_no_size(tmp_path):
    inf, nan = float("inf"), float("nan")
    padded = bytearray(wav_bytes(48000, 32, [[1 << 20, -(1 << 20), 1 << 21, 0]]))
    padded[34:36] = struct.pack("<H", 24)  # the header now says 24 bits in 4 bytes a frame
    unstated = bytearray(wav_bytes(48000, 16, [[16384, -16384]]))
    unstated[32:34] = b"\0\0"  # a writer that left the block align empty
    bad = {
        "inf": wav_bytes(48000, 32, [[0.0, 0.5, inf, 0.25]], kind=3),
        "negInf": wav_bytes(48000, 32, [[0.0, -inf]], kind=3),
        "nan": wav_bytes(48000, 32, [[nan, 0.5]], kind=3),
        "nan64": wav_bytes(48000, 64, [[0.5, nan]], kind=3),
        "huge64": wav_bytes(48000, 64, [[0.5, 1e300]], kind=3),  # finite as a double, infinite as the float32 sample it becomes
        "padded": bytes(padded),
    }
    good = {
        "unstated": bytes(unstated),
        "f64": wav_bytes(48000, 64, [[0.5, -0.25]], kind=3),
        "zeroSize": wav_bytes(48000, 16, [[16384, -16384, 8192]], claim=0),  # the other mark of a writer that never went back
        "zeroSizeSilence": wav_bytes(48000, 16, [[0, 0, 0, 16384]], claim=0),
        "zeroSizeLikeChunk": wav_bytes(48000, 16, [[0x494C, 0x5453, 32767, 32767]], claim=0),  # samples that spell LIST, then a size no file holds
        "emptyThenList": wav_bytes(48000, 16, [[]]) + chunk(b"LIST", b"abcd"),  # a data chunk that really is empty, with a chunk after it
        "emptyLast": wav_bytes(48000, 16, [[]]),
    }
    b64 = lambda d: json.dumps({k: base64.b64encode(v).decode() for k, v in d.items()})
    got = run("const good = " + b64(good) + ", bad = " + b64(bad) + """;
    const read = Object.fromEntries(Object.entries(good).map(([k, v]) => [k, M.readWav(Buffer.from(v, 'base64')).chans.map((c) => Array.from(c))]));
    const errors = Object.fromEntries(Object.entries(bad).map(([k, v]) => { try { M.readWav(Buffer.from(v, 'base64')); return [k, 'read']; } catch (e) { return [k, e.message]; } }));
    console.log(JSON.stringify({ read, errors }));""")
    assert got["read"] == {"unstated": [[0.5, -0.5]], "f64": [[0.5, -0.25]], "zeroSize": [[0.5, -0.5, 0.25]], "zeroSizeSilence": [[0, 0, 0, 0.5]],
                           "zeroSizeLikeChunk": [[0x494C / 32768, 0x5453 / 32768, 32767 / 32768, 32767 / 32768]], "emptyThenList": [[]], "emptyLast": [[]]}
    assert all("non-finite" in got["errors"][k] for k in ("inf", "negInf", "nan", "nan64", "huge64")), got["errors"]
    assert got["errors"]["padded"].startswith("unsupported WAV format")

    # On the command line: a render that blew up is not a quiet clean file, and a full-scale stream with size 0 is not an empty one.
    blown = tmp_path / "blown.wav"
    blown.write_bytes(wav_bytes(48000, 32, [[0.01 * math.sin(i / 10) if i < 12000 else inf for i in range(24000)]], kind=3))
    out = cli(blown)
    assert out.returncode == 2 and out.stdout == "" and out.stderr.startswith("asset_lint: WAV holds non-finite samples")
    stream = tmp_path / "stream.wav"
    stream.write_bytes(wav_bytes(48000, 16, [[round(32767 * math.sin(2 * math.pi * 440 * i / 48000)) for i in range(24000)]], claim=0))
    out = cli(stream, "--json")
    assert out.returncode == 1 and abs(json.loads(out.stdout)["measure"]["seconds"] - 0.5) < 1e-9
    assert [x["id"] for x in json.loads(out.stdout)["issues"]] == ["peak", "clip"]


def test_eight_bit_files_clip_on_their_own_top_value():
    data = [255] * 50 + [128] * 50 + [0] * 10 + [1] * 5 + [254] * 5 + [128] * 30
    got = run("const w = M.readWav(Buffer.from('" + base64.b64encode(wav_bytes(8000, 8, [data])).decode() + """', 'base64'));
    const top = Float32Array.from({ length: 100 }, (_, i) => (i % 2 ? 127 / 128 : 0)), wide = Float32Array.of(0, 32767 / 32768, 32766 / 32768, -1, 0);
    const as = (bits, x) => M.measure({ rate: 8000, bits, chans: [x] }).clips;
    console.log(JSON.stringify({ bits: w.bits, u8: M.measure(w).clips, lint: ids(sound({ kind: 'sfx' }, M.measure(w))).slice(0, 2),
      sameValueElsewhere: [as(undefined, top), as(16, top), as(32, top)], rail16: [as(8, wide), as(16, wide), as(24, wide), as(32, wide), as(null, wide)] }));""")
    # 255 is as high as an 8-bit sample goes (127/128). Held to the 16-bit rail it could never clip upward.
    assert got["bits"] == 8 and got["u8"] == 65 and got["lint"] == ["peak", "clip"]
    assert got["sameValueElsewhere"] == [0, 0, 0] and got["rail16"] == [3, 2, 2, 2, 2]


def test_seam_is_the_edge_step_over_the_slope_99_in_100_steps_stay_under():
    got = run("""
    let r = 99; const rnd = () => { r = (r * 16807) % 2147483647; return r / 1073741824 - 1; };
    const sorted = (x) => { const d = Float64Array.from({ length: x.length - 1 }, (_, i) => Math.abs(x[i + 1] - x[i])).sort(); return Math.abs(x[0] - x[x.length - 1]) / Math.max(d[Math.floor(d.length * 0.99)], 1e-4); };
    const sounds = {
      noise: Float32Array.from({ length: 50000 }, () => 0.4 * rnd()),
      click: Float32Array.from({ length: 50000 }, (_, i) => (i === 700 ? 1 : 0.02 * Math.sin(i / 40) + 0.3)),  // one huge step among small ones
      steps: Float32Array.from({ length: 1000 }, (_, i) => (i % 100 < 2 ? 0.5 : -0.25)),
      flat: Float32Array.from({ length: 1000 }, (_, i) => (i < 500 ? 0.25 : 0.2)),
      pair: Float32Array.of(0.5, -0.25),
    };
    console.log(JSON.stringify(Object.fromEntries(Object.entries(sounds).map(([k, x]) => [k, [one(x).seam, sorted(x)]]))));""")
    assert set(got) == {"noise", "click", "steps", "flat", "pair"}
    for name, (seam, exact) in got.items():  # measure counts the slopes into bins; a full sort of them gives the same number
        assert abs(seam - exact) <= 1e-6 * exact, name


def test_id_rule_with_no_separator_or_a_letter_for_one_answers_at_once(tmp_path):
    got = run("""
    const glued = { pattern: '{kind}{name}', sep: '' }, lettered = { pattern: '{kind}_{name}', sep: 'x' }, long = 'a'.repeat(60);
    // The patterns the asset room builds today for these two rules, tried on ids short enough for them to finish.
    const today = { glued: /^(?:sfx|amb|bgm)[a-z0-9]+(?:[a-z0-9]+)*(?:\\d+)?$/, lettered: /^(?:sfx|amb|bgm)_[a-z0-9]+(?:x[a-z0-9]+)*(?:x\\d+)?$/ };
    const short = ['sfxhit', 'sfxhit2', 'sfx', 'sfx_hit', 'hit', 'bgmtitle01', 'sfxHit', 'sfx hit', 'sfx_boxxcar', 'sfx_axb', 'sfx_ax', 'sfx_x', 'sfx_ax3', 'sfx_a_b', 'amb_x1x2', ''];
    console.log(JSON.stringify({
      glued: ['sfx' + long + '!', 'sfx' + long + ' (copy)', 'sfx' + long, 'sfx' + long + '7'].map((id) => M.idOk(id, glued)),
      lettered: ['sfx_' + 'ax'.repeat(40) + '!', 'sfx_' + 'ax'.repeat(40) + 'a'].map((id) => M.idOk(id, lettered)),
      same: short.filter((id) => M.idOk(id, glued) !== today.glued.test(id) || M.idOk(id, lettered) !== today.lettered.test(id)),
      some: [M.idOk('sfxhit2', glued), M.idOk('sfx_hit', glued), M.idOk('sfx_boxxcar', lettered), M.idOk('sfx_a_b', lettered)],
    }));""")
    assert got["glued"] == [False, False, True, True] and got["lettered"] == [False, True]
    assert got["same"] == [] and got["some"] == [True, False, True, False]

    path = write_wav(tmp_path / "fine.wav", [tone(48000, 440, 0.3, 0.5, fade=0.01)])
    spec = tmp_path / "glued.json"
    spec.write_text(json.dumps({"id_rule": {"pattern": "{kind}{name}", "sep": "", "check": True}, "categories": [], "assets": []}), encoding="utf-8")
    wrong = cli(path, "--json", "--spec", spec, "--id", "sfxplayerfootstepgrassconcretewet01 (copy)")
    assert wrong.returncode == 1 and [x["id"] for x in json.loads(wrong.stdout)["issues"]] == ["name"]
    assert json.loads(cli(path, "--json", "--spec", spec, "--id", "sfxplayerfootstepgrassconcretewet01").stdout)["issues"] == []


def test_command_line_takes_a_file_named_like_an_option_after_two_dashes(tmp_path):
    clean = tone(48000, 440, 0.3, 0.5, fade=0.01)
    write_wav(tmp_path / "--x.wav", [clean])
    fine = write_wav(tmp_path / "fine.wav", [clean])
    out = cli("--json", "--", "--x.wav", cwd=tmp_path)
    assert out.returncode == 0 and json.loads(out.stdout)["file"] == "--x.wav" and json.loads(out.stdout)["issues"] == []
    assert json.loads(cli("--json", "--id=--json", fine).stdout)["id"] == "--json"  # said on purpose with =
    # Without the two dashes it is an unknown option, after them --json is a file that is not there, and an option is never taken as a value.
    for args in (["--x.wav"], ["--", "--json"], [fine, "--id", "--json"], [fine, "--kind", "--loop"], [fine, "--id", "--"], [fine, "--", fine], ["--"]):
        failed = cli(*args, cwd=tmp_path)
        assert failed.returncode == 2 and failed.stdout == "" and failed.stderr.startswith("asset_lint: "), args
    assert "--id needs a value" in cli(fine, "--id", "--json").stderr
