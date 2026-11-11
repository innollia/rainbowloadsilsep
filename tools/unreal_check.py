"""Headless Unreal check of the Unreal export (docs/ASSET_UNREAL_SPEC.md I2). Not collected by pytest.

    python tools/unreal_check.py [--work DIR] [--prepare-only]

Builds a blank project in a temporary folder, writes the bundle with unreal.js under Node, makes the WAVs, then runs
Unreal three times, one process at a time, each with a 600 s limit (only the process started here is ever stopped):
  1. commandlet import            2. commandlet: read state, import again, read state again
  3. plain editor start (no Python flag) with OLMUSE_QUIT_AFTER=2: import at start, then a second import from the
     watch after this script changes olmuse_build.json while the editor runs.
Prints one line per check and exits 1 if any failed. Engine: env OLMUSE_UE_CMD or the UE 5.8 default path.
"""
import argparse, json, math, os, pathlib, shutil, struct, subprocess, sys, tempfile, time, wave

REPO = pathlib.Path(__file__).resolve().parents[1]
STUDIO = REPO / "studio_frontend" / "asset_studio"
UE = os.environ.get("OLMUSE_UE_CMD", "C:/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor-Cmd.exe")
LIMIT = 600

# Fixed input: 4 sounds (one Korean id, one id with a dot, one mono), an ambience (bed 2 + scatter 1) and music (stem 2),
# two parameters, one with a Korean id. Files follow app.js exportPath: <folder>/<id>.wav.
PROJECT = {
    "game": "숲의 노래",
    "assets": [
        {"id": "amb_wind", "name": "바람", "category": "amb", "loop": True, "file": "audio/amb_wind.wav"},
        {"id": "빗소리", "name": "빗소리", "category": "amb", "loop": True, "file": "audio/빗소리.wav"},
        {"id": "sfx.bird", "name": "새", "category": "sfx", "loop": False, "file": "audio/sfx.bird.wav"},
        {"id": "bgm_drums", "name": "북", "category": "music", "loop": False, "file": "audio/bgm_drums.wav"},
    ],
    "dynamics": [
        {"id": "dyn_1", "name": "숲", "type": "ambience",
         "params": [{"id": "intensity", "name": "강도", "min": 0, "max": 1, "default": 0.5}],
         "layers": [
             {"asset": "amb_wind", "role": "bed", "param": None, "on": [0, 1], "volume": 1},
             {"asset": "빗소리", "role": "bed", "param": "intensity", "on": [0.3, 0.8], "volume": 0.8},
             {"asset": "sfx.bird", "role": "scatter", "param": "intensity", "on": [0.5, 1], "volume": 1,
              "scatter": {"min_gap": 1, "max_gap": 3, "pitch": [0.9, 1.1], "pan": [-0.8, 0.8]}}]},
        {"id": "dyn_2", "name": "전투 음악", "type": "music", "bpm": 120, "beats_per_bar": 4,
         "params": [{"id": "긴장", "name": "긴장", "min": 0, "max": 1, "default": 0}],
         "layers": [
             {"asset": "bgm_drums", "role": "stem", "param": None, "on": [0, 1], "volume": 1},
             {"asset": "amb_wind", "role": "stem", "param": "긴장", "on": [0, 1], "volume": 1}]},
    ],
}
SECONDS = {"amb_wind": (2, 2.0, 220), "빗소리": (2, 2.0, 330), "sfx.bird": (1, 0.5, 880), "bgm_drums": (2, 2.0, 110)}

PROJECT_INIT = """import os, unreal
d = os.path.join(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()), 'Saved')
os.makedirs(d, exist_ok=True)
open(os.path.join(d, 'project_init.marker'), 'w').write('ran')
"""

# Reads the state of /Game/Olmuse. Run 2: as -script (state, run() again, state). Run 3: from the watch after each import.
INSPECT = r'''
import json, os, re, sys
sys.dont_write_bytecode = True
import unreal
ROOT = os.path.abspath(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
EAL = unreal.EditorAssetLibrary
OUT = os.path.join(ROOT, 'Saved', 'OlmuseCheck')
os.makedirs(OUT, exist_ok=True)

def state(tag):
    reg = unreal.AssetRegistryHelpers.get_asset_registry()
    reg.scan_paths_synchronous(['/Game/Olmuse'], True)
    s = {'assets': {}, 'uassets': {}}
    for ad in reg.get_assets_by_path('/Game/Olmuse', recursive=True) or []:
        pkg = str(ad.get_editor_property('package_name'))
        cls = str(ad.get_editor_property('asset_class_path').get_editor_property('asset_name'))
        a = EAL.load_asset(pkg)
        info = {'class': cls}
        if cls == 'SoundWave':
            for p in ('looping', 'duration', 'num_channels'):
                info[p] = a.get_editor_property(p)
            info['OlmuseId'] = EAL.get_metadata_tag(a, 'OlmuseId')
        elif cls == 'MetaSoundSource':
            esub = unreal.get_editor_subsystem(unreal.MetaSoundEditorSubsystem)
            b = esub.find_or_begin_building(a)[0]
            names = b.get_graph_input_names()
            names = names[0] if isinstance(names, tuple) else names
            info['inputs'] = sorted(str(n) for n in names)
            info['defaults'] = {}
            for n in info['inputs']:
                if n.startswith('UE.'):
                    continue
                lit = b.get_graph_input_default(n)
                lit = lit[0] if isinstance(lit, tuple) else lit
                m = re.search(r'AsFloat=\(([-0-9.e]+)', lit.export_text())
                info['defaults'][n] = float(m.group(1)) if m else lit.export_text()
            info['own_nodes'] = len([x for x in (EAL.get_metadata_tag(a, 'OlmuseNodes') or '').split('|') if x])
            t = unreal.AssetExportTask()
            path = os.path.join(OUT, '%s.%s.t3d' % (pkg.split('/')[-1], tag))
            t.set_editor_property('object', a)
            t.set_editor_property('filename', path)
            t.set_editor_property('automated', True)
            t.set_editor_property('prompt', False)
            t.set_editor_property('replace_identical', True)
            t.set_editor_property('exporter', unreal.ObjectExporterT3D())
            unreal.Exporter.run_asset_export_task(t)
            text = open(path, encoding='utf-8', errors='replace').read()
            info['t3d_nodes'] = text.count(',ClassID=')
            info['t3d_edges'] = text.count('FromNodeID')
        s['assets'][pkg] = info
    base = os.path.join(ROOT, 'Content', 'Olmuse')
    for r, _d, fs in os.walk(base):
        for f in fs:
            p = os.path.join(r, f)
            s['uassets'][os.path.relpath(p, base).replace(os.sep, '/')] = [os.path.getsize(p), os.path.getmtime(p)]
    return s

def dump(name, data):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)

if __name__ == 'olmuse_after_import':
    n = len([f for f in os.listdir(OUT) if f.startswith('after_import_')]) + 1
    dump('after_import_%d.json' % n, state('after%d' % n))
else:
    sys.path.insert(0, os.path.join(ROOT, 'Plugins', 'OlmuseAudio', 'Content', 'Python'))
    import olmuse_unreal
    a = state('a')
    r = olmuse_unreal.run(ROOT)
    dump('run2.json', {'before': a, 'result': r, 'after': state('b')})
'''


def node_build(project):
    """unreal_py.js + unreal.js under Node, the way the page loads them."""
    src = "globalThis.window = globalThis;\n" + (STUDIO / "unreal_py.js").read_text(encoding="utf-8") + "\n" + \
        (STUDIO / "unreal.js").read_text(encoding="utf-8") + \
        "\nprocess.stdout.write(JSON.stringify(window.unrealExport.build(" + json.dumps(project, ensure_ascii=False) + ")));\n"
    out = subprocess.run(["node", "-"], input=src, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    return json.loads(out.stdout)


def write_bundle(work, project):
    for f in node_build(project):
        p = work / f["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(f["text"].encode("utf-8"))


def make_wav(path, channels, seconds, freq):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(48000 * seconds)
    frames = bytearray()
    for i in range(n):
        frames += struct.pack("<h", int(6000 * math.sin(2 * math.pi * freq * i / 48000))) * channels
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels); w.setsampwidth(2); w.setframerate(48000); w.writeframes(bytes(frames))


def prepare(work):
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "Check.uproject").write_text('{"FileVersion": 3, "EngineAssociation": "5.8", "Plugins": []}\n', encoding="utf-8")
    (work / "Content" / "Python").mkdir(parents=True)
    (work / "Content" / "Python" / "init_unreal.py").write_text(PROJECT_INIT, encoding="utf-8")
    (work / "olmuse_inspect.py").write_text(INSPECT, encoding="utf-8")
    write_bundle(work, PROJECT)
    for a in PROJECT["assets"]:
        ch, sec, hz = SECONDS[a["id"]]
        make_wav(work / "OlmuseAudio" / a["file"], ch, sec, hz)


def unreal(work, tag, args, env=None, during=None):
    """One Unreal process, at most LIMIT seconds. during(proc) may run while it is up. Returns (exit code, seconds)."""
    log = work / "Saved" / "OlmuseCheck" / (tag + ".log")
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [UE, str(work / "Check.uproject"), *args, "-nosplash", "-stdout", "-abslog=" + str(log)]
    t0 = time.time()
    with open(log.with_suffix(".stdout.txt"), "wb") as so:
        proc = subprocess.Popen(cmd, stdout=so, stderr=subprocess.STDOUT, env={**os.environ, **(env or {})})
        try:
            if during:
                during(proc, t0)
            rc = proc.wait(timeout=max(1, LIMIT - (time.time() - t0)))
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
            proc.wait()
            rc = "timeout"
    return rc, round(time.time() - t0, 1)


class Judge:
    def __init__(self):
        self.fails = 0

    def __call__(self, ok, what, detail=""):
        print(("PASS " if ok else "FAIL ") + what + (("  [" + str(detail) + "]") if detail != "" else ""), flush=True)
        if not ok:
            self.fails += 1
        return ok


def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def expected():
    """The bundle's own data: asset names, loop flags, inputs and defaults per MetaSound."""
    b = [f for f in node_build(PROJECT) if f["path"].endswith("olmuse_build.json")][0]
    return json.loads(b["text"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default=os.path.join(tempfile.gettempdir(), "olmuse_unreal_check"))
    ap.add_argument("--prepare-only", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    work = pathlib.Path(a.work).resolve()
    prepare(work)
    print("project:", work, flush=True)
    if a.prepare_only:
        return 0
    J = Judge()
    exp = expected()
    sound_paths = {"/Game/Olmuse/Audio/" + s["asset"]: s for s in exp["sounds"]}
    dyn_paths = {"/Game/Olmuse/Dynamic/" + d["asset"]: d for d in exp["dynamics"]}
    importer = work / "Plugins/OlmuseAudio/Content/Python/olmuse_unreal.py"
    result = work / "Saved/Olmuse/last_import.json"
    out = work / "Saved/OlmuseCheck"

    # 1. commandlet import
    rc, sec = unreal(work, "run1", ["-run=pythonscript", "-script=" + str(importer), "-unattended"])
    r1 = read(result) if result.exists() else {}
    J(rc == 0, "run 1 commandlet exit code 0", "%s, %ss" % (rc, sec))
    J(r1.get("ok") is True, "run 1 last_import ok", r1.get("messages") or r1.get("error"))
    J(sorted(r1.get("sounds", {}).get("imported", [])) == sorted(s["id"] for s in exp["sounds"]), "run 1 imported 4 sounds", r1.get("sounds"))
    J(sorted(r1.get("dynamics", {}).get("built", [])) == sorted(d["id"] for d in exp["dynamics"]), "run 1 built 2 MetaSounds", r1.get("dynamics"))

    # 2. read state, import again, read state
    rc, sec = unreal(work, "run2", ["-run=pythonscript", "-script=" + str(work / "olmuse_inspect.py"), "-unattended"])
    J(rc == 0, "run 2 commandlet exit code 0", "%s, %ss" % (rc, sec))
    r2 = read(out / "run2.json") if (out / "run2.json").exists() else {"before": {"assets": {}, "uassets": {}}, "result": {}, "after": {"assets": {}, "uassets": {}}}
    st = r2["before"]["assets"]
    waves = {p: v for p, v in st.items() if v["class"] == "SoundWave"}
    J(sorted(waves) == sorted(sound_paths), "4 SoundWaves under A3 names", sorted(waves))
    J(all(bool(waves[p]["looping"]) == bool(sound_paths[p]["loop"]) for p in waves if p in sound_paths),
      "looping True only for loop sounds", {p: waves[p]["looping"] for p in waves})
    J(any(v["num_channels"] == 1 for v in waves.values()), "the mono WAV imported as 1 channel", {p: v["num_channels"] for p, v in waves.items()})
    mss = {p: v for p, v in st.items() if v["class"] == "MetaSoundSource"}
    J(sorted(mss) == sorted(dyn_paths), "2 MetaSound Sources", sorted(mss))
    for p, d in dyn_paths.items():
        m = mss.get(p, {})
        want = sorted([x["input"] for x in d["params"]] + ["UE.Source.OnPlay"])
        J(m.get("inputs") == want, "%s graph inputs" % d["asset"], m.get("inputs"))
        J(all(abs(m.get("defaults", {}).get(x["input"], -99) - x["default"]) < 1e-6 for x in d["params"]), "%s input defaults" % d["asset"], m.get("defaults"))
        J(m.get("own_nodes", 0) > 0, "%s OlmuseNodes not empty" % d["asset"], m.get("own_nodes"))
        print("     %s: %s own nodes, text export %s nodes / %s edges" % (d["asset"], m.get("own_nodes"), m.get("t3d_nodes"), m.get("t3d_edges")))
    r = r2["result"]
    J(r.get("sounds", {}).get("imported") == [] and not r.get("sounds", {}).get("failed"), "second run imported 0 sounds", r.get("sounds"))
    J(not r.get("dynamics", {}).get("built") and not r.get("dynamics", {}).get("updated") and not r.get("dynamics", {}).get("failed"),
      "second run built/updated 0 MetaSounds", r.get("dynamics"))
    J(r2["before"]["assets"] == r2["after"]["assets"], "assets and node counts unchanged by the second run")
    J(r2["before"]["uassets"] == r2["after"]["uassets"], ".uasset files unchanged (names, sizes, times)", len(r2["after"]["uassets"]))
    before = r2["after"]

    # 3. plain editor start + watch
    changed = json.loads(json.dumps(PROJECT))
    changed["dynamics"][0]["layers"][1]["volume"] = 0.5          # ambience data changes
    write_bundle(work, changed)
    make_wav(work / "OlmuseAudio/audio/amb_wind.wav", 2, 3.0, 220)  # a sound changes length
    (work / "OlmuseAudio/audio/bgm_drums.wav").write_bytes(b"not a wav file at all" * 100)  # a sound cannot import
    rec_before = read(work / "Plugins/OlmuseAudio/imported.json")
    marker = work / "Saved/project_init.marker"
    if marker.exists():
        marker.unlink()
    second = json.loads(json.dumps(changed))
    second["dynamics"][1]["params"][0]["default"] = 0.25         # changed while the editor runs

    def during(proc, t0):
        flag = work / "Saved/Olmuse/watch_run_1.json"
        while proc.poll() is None and time.time() - t0 < LIMIT - 60:
            if flag.exists():
                time.sleep(3)
                write_bundle(work, second)
                return
            time.sleep(1)

    env = {"OLMUSE_QUIT_AFTER": "2", "OLMUSE_AFTER_IMPORT": str(work / "olmuse_inspect.py")}
    rc, sec = unreal(work, "run3", ["-nullrhi"], env=env, during=during)
    J(rc != "timeout", "run 3 editor closed by itself", "%s, %ss" % (rc, sec))
    w1 = read(work / "Saved/Olmuse/watch_run_1.json") if (work / "Saved/Olmuse/watch_run_1.json").exists() else {}
    w2 = read(work / "Saved/Olmuse/watch_run_2.json") if (work / "Saved/Olmuse/watch_run_2.json").exists() else {}
    s1 = read(out / "after_import_1.json") if (out / "after_import_1.json").exists() else {"assets": {}}
    s2 = read(out / "after_import_2.json") if (out / "after_import_2.json").exists() else {"assets": {}}
    wind = "/Game/Olmuse/Audio/amb_wind"
    drums = "/Game/Olmuse/Audio/bgm_drums"
    J(w1.get("sounds", {}).get("imported") == ["amb_wind"], "start import: only the changed WAV re-imported", w1.get("sounds"))
    J(abs(s1["assets"].get(wind, {}).get("duration", 0) - 3.0) < 0.01 and s1["assets"].get(wind, {}).get("looping") is True,
      "changed WAV: new length 3.0 s, looping kept", s1["assets"].get(wind))
    J([x["id"] for x in w1.get("sounds", {}).get("failed", [])] == ["bgm_drums"], "broken WAV reported failed", w1.get("sounds", {}).get("failed"))
    J(s1["assets"].get(drums) == before["assets"].get(drums), "broken WAV: old asset kept", s1["assets"].get(drums))
    rec1 = read(work / "Plugins/OlmuseAudio/imported.json")
    J(rec1["sounds"]["bgm_drums"]["hash"] == rec_before["sounds"]["bgm_drums"]["hash"], "broken WAV: record keeps the old hash")
    J(rec1["sounds"]["amb_wind"]["hash"] != rec_before["sounds"]["amb_wind"]["hash"], "changed WAV: record has the new hash")
    amb, mus = "/Game/Olmuse/Dynamic/" + exp["dynamics"][0]["asset"], "/Game/Olmuse/Dynamic/" + exp["dynamics"][1]["asset"]
    J(w1.get("dynamics", {}).get("updated") == ["dyn_1"] and w1.get("dynamics", {}).get("unchanged") == ["dyn_2"],
      "start import: only the changed dynamic rebuilt", w1.get("dynamics"))
    # An in-place rebuild drops the "Input Template" node build_to_asset puts beside each graph input (one node, one
    # edge per parameter) and never adds it back, so the first rebuild may be smaller by that much; it must never grow.
    def same_graph(old, new, n_params, what):
        for k in ("own_nodes", "inputs"):
            J(new.get(k) == old.get(k), "%s: same %s" % (what, k), (old.get(k), new.get(k)))
        for k in ("t3d_nodes", "t3d_edges"):
            J(old.get(k, -1) - n_params <= new.get(k, -2) <= old.get(k, -1), "%s: %s not grown" % (what, k), (old.get(k), new.get(k)))
    same_graph(before["assets"].get(amb, {}), s1["assets"].get(amb, {}), len(exp["dynamics"][0]["params"]), "rebuilt dynamic")
    J(w2.get("dynamics", {}).get("updated") == ["dyn_2"] and w2.get("sounds", {}).get("imported") == [],
      "watch import while the editor runs: the changed dynamic only", (w2.get("sounds"), w2.get("dynamics")))
    same_graph(s1["assets"].get(mus, {}), s2["assets"].get(mus, {}), len(exp["dynamics"][1]["params"]), "watch-rebuilt dynamic")
    d2 = s2["assets"].get(mus, {}).get("defaults", {})
    J(abs(list(d2.values() or [-1])[0] - 0.25) < 1e-6, "watch import: new default in the graph", d2)
    J(marker.exists(), "project's own init_unreal.py ran too")
    J(not (work / "Plugins/OlmuseAudio/Content/Python/__pycache__").exists(), "no __pycache__ in the plugin")
    print("%d check(s) failed" % J.fails if J.fails else "all checks passed", flush=True)
    return 1 if J.fails else 0


if __name__ == "__main__":
    sys.exit(main())
