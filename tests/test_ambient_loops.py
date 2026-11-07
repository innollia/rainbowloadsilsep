"""Ambience has to run on forever: every loop stays level across its seam and never dips out."""
import json, pathlib, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"
SCRIPT = """
globalThis.window = globalThis;
%s
%s
const { ASSETS, RULES } = window.STUDIO_DATA;
const synth = window.synth;
const out = {};
for (const a of ASSETS.filter((x) => x.id.startsWith('amb_'))) {
  for (const change of [{}, { shift: 1.12, stretch: 0.88 }, { shift: 0.8, stretch: 1.3 }]) {
    const sound = synth.render(a, change), m = synth.measure(sound);
    const failed = RULES.filter((r) => !r.text && (!r.applies || r.applies(a)) && r.bad(r.read(m, a), r)).map((r) => r.id);
    out[a.id + JSON.stringify(change)] = { seconds: m.seconds, seam: m.seam, wrap: m.wrap, dip: m.dip, peak: m.peak, failed };
  }
}
console.log(JSON.stringify(out));
"""


def measured():
    script = SCRIPT % ((ROOT / "data.js").read_text(encoding="utf-8"), (ROOT / "synth.js").read_text(encoding="utf-8"))
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(run.stdout)


def test_every_ambience_loops_without_a_seam_or_a_gap():
    results = measured()
    assert len(results) == 12
    for name, m in results.items():
        assert m["failed"] == [], (name, m)


def test_no_loop_has_a_seam():
    script = SCRIPT.split("const out = {};")[0] % ((ROOT / "data.js").read_text(encoding="utf-8"), (ROOT / "synth.js").read_text(encoding="utf-8")) + """
    const bad = [];
    for (const a of ASSETS) {
      const m = synth.measure(synth.render(a));
      for (const r of RULES) if (r.id === 'seam' && r.applies(a) && r.bad(r.read(m, a), r)) bad.push([a.id, m.seam]);
    }
    console.log(JSON.stringify(bad));
    """
    run = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(run.stdout) == []


def test_ambience_is_long_enough_not_to_sound_repeated():
    assert all(m["seconds"] >= 7 for m in measured().values())
