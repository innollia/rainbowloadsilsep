"""Ambience has to run on forever: every loop stays level across its seam and never dips out."""
import json, pathlib, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"
LEGACY = pathlib.Path(__file__).parent / "js" / "legacy_sounds.js"
FILES = ("data.js", "synth.js", "measure.js")
# The stand-in sounds that boards saved by earlier pages hold (tests/js/legacy_sounds.js) are judged by the one table the room, the command line and the server use (assetMeasure.lint).
# Only the rules about the sound itself count here: its id and its sources say nothing about how it loops.
HEAD = """
const { ASSETS } = window.LEGACY_SOUNDS;
const synth = window.synth, M = window.assetMeasure;
const ofSound = new Set(M.RULES.filter((r) => !r.text).map((r) => r.id));
const failedOf = (a, m) => M.lint({ music: !!a.music, loop: !!a.loop, id: a.id }, m).filter((i) => ofSound.has(i.id)).map((i) => i.id);
"""
EVERY_AMBIENCE = """
const out = {};
for (const a of ASSETS.filter((x) => x.id.startsWith('amb_'))) {
  for (const change of [{}, { shift: 1.12, stretch: 0.88 }, { shift: 0.8, stretch: 1.3 }]) {
    const sound = synth.render(a, change), m = synth.measure(sound);
    out[a.id + JSON.stringify(change)] = { seconds: m.seconds, seam: m.seam, wrap: m.wrap, dip: m.dip, peak: m.peak, failed: failedOf(a, m) };
  }
}
console.log(JSON.stringify(out));
"""


def node(body):
    src = "globalThis.window = globalThis;\n" + "\n;\n".join((ROOT / f).read_text(encoding="utf-8") for f in FILES) + "\n;\n" + LEGACY.read_text(encoding="utf-8") + "\n;\n" + HEAD + body
    run = subprocess.run(["node", "-"], input=src, capture_output=True, text=True, encoding="utf-8", check=True)  # stdin: Windows caps a command line at 32K
    return json.loads(run.stdout)


def measured():
    return node(EVERY_AMBIENCE)


def test_every_ambience_loops_without_a_seam_or_a_gap():
    results = measured()
    assert len(results) == 12
    for name, m in results.items():
        assert m["failed"] == [], (name, m)


def test_no_loop_has_a_seam():
    bad = node("""
    const bad = [];
    for (const a of ASSETS) {
      const m = synth.measure(synth.render(a));
      if (failedOf(a, m).includes('seam')) bad.push([a.id, m.seam]);
    }
    console.log(JSON.stringify(bad));
    """)
    assert bad == []


def test_the_seam_rule_is_judged_on_loops_and_only_there():
    """The table the test reads is the one that judges: a loop whose ends do not meet fails, the same sound played once does not."""
    got = node("""
    const m = { ...synth.measure(synth.render(ASSETS.find((a) => a.id === 'amb_wind'))), seam: 99, wrap: 99, dip: 99 };
    console.log(JSON.stringify({ loop: failedOf({ loop: true }, m), once: failedOf({ loop: false }, m).filter((id) => ['seam', 'wrap', 'steady'].includes(id)), music: failedOf({ loop: true, music: true }, m).filter((id) => ['seam', 'wrap', 'steady'].includes(id)) }));
    """)
    assert got == {"loop": ["seam", "wrap", "steady"], "once": [], "music": ["seam"]}


def test_ambience_is_long_enough_not_to_sound_repeated():
    assert all(m["seconds"] >= 7 for m in measured().values())
