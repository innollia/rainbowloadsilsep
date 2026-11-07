"""A cover must keep moving while a song plays, even when the song's bands are silent."""
import json, pathlib, subprocess

ART = pathlib.Path(__file__).parents[1] / "studio_frontend" / "art.js"


def test_breathing_survives_rounding():
    script = """
    const window = {}; const self = window; globalThis.window = window;
    %s
    const art = window.albumArt || globalThis.albumArt;
    const attrs = {'data-pulse': 1};
    const made = {dataset: {pulse: '0.05'}, value: '', setAttribute(k, v) { this.value = v; }, removeAttribute() {}};
    const root = {querySelectorAll: () => [made]};
    const seen = new Set();
    for (let start = 0; start < 1; start += 0.01) {
      art.move(root, start, null, false); const a = made.value;
      art.move(root, start + 0.25, null, false);
      if (a === made.value) seen.add(start);
    }
    console.log(JSON.stringify(seen.size));
    """ % ART.read_text(encoding="utf-8")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(out.stdout) <= 1
