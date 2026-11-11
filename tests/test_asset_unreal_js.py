"""The Unreal bundle (unreal_py.js + unreal.js) under Node: paths, the plugin descriptor, asset and input names, the numbers
in olmuse_build.json (levels, scatter, fades, bars), skipped layers, the same text for the same input, and the README
(docs/ASSET_UNREAL_SPEC.md A, C, H)."""
import json, pathlib, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"


def node(script, timeout=60):
    out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", check=True, timeout=timeout)
    return json.loads(out.stdout)


def run(body, py=True):
    src = "globalThis.window = globalThis;\n"
    if py:
        src += (ROOT / "unreal_py.js").read_text(encoding="utf-8") + "\n"
    src += (ROOT / "unreal.js").read_text(encoding="utf-8") + "\nconst U = window.unrealExport; let out;\n" + body + \
        "\nprocess.stdout.write(JSON.stringify(out));\n"
    return node(src)


def bundle(project):
    return run("out = U.build(%s);" % json.dumps(project, ensure_ascii=False))


def data(project):
    files = bundle(project)
    return json.loads(files[-1]["text"])


def asset(i, loop=False, **kw):
    return {"id": i, "name": kw.get("name", i), "category": "amb", "loop": loop, "file": "audio/%s.wav" % i, **kw}


BASE = {
    "game": "숲의 노래",
    "assets": [asset("amb_wind", True, name="바람"), asset("sfx_bird"), asset("amb_rain", True)],
    "dynamics": [{"id": "dyn_1", "name": "숲", "type": "ambience",
                  "params": [{"id": "intensity", "name": "강도", "min": 0, "max": 1, "default": 0.5}],
                  "layers": [{"asset": "amb_wind", "role": "bed", "param": None, "on": [0, 1], "volume": 1},
                             {"asset": "amb_rain", "role": "bed", "param": "intensity", "on": [0.3, 0.8], "volume": 1},
                             {"asset": "sfx_bird", "role": "scatter", "param": "intensity", "on": [0, 1], "volume": 1,
                              "scatter": {"min_gap": 2, "max_gap": 8, "pitch": [0.9, 1.1], "pan": [-0.8, 0.8]}}]}],
}


def dyn_with(layers, params=None, **kw):
    d = {"id": "d", "name": "d", "type": "ambience", "params": params if params is not None else [{"id": "x", "name": "x", "min": 0, "max": 1, "default": 0}], "layers": layers}
    d.update(kw)
    return d


def test_paths_and_order():
    files = bundle(BASE)
    paths = [f["path"] for f in files]
    assert paths == ["Plugins/OlmuseAudio/OlmuseAudio.uplugin", "Plugins/OlmuseAudio/Content/Python/init_unreal.py",
                     "Plugins/OlmuseAudio/Content/Python/olmuse_unreal.py", "OlmuseAudio/README.md", "Plugins/OlmuseAudio/olmuse_build.json"]
    assert not any(p.startswith(("godot/", "Content/", "Config/")) or p.endswith("imported.json") for p in paths)
    assert all("/" in p for p in paths), "nothing at the project top"


def test_python_text_is_passed_through_and_required():
    files = bundle(BASE)
    py = run("out = window.unrealPy;")
    assert files[1]["text"] == py["INIT"] and files[2]["text"] == py["IMPORTER"]
    err = run("try { U.build({}); out = 'built'; } catch (e) { out = e.message; }", py=False)
    assert err == "unreal_py.js"


def test_uplugin():
    d = json.loads(bundle(BASE)[0]["text"])
    assert "Modules" not in d
    assert d == {"FileVersion": 3, "Version": 1, "VersionName": "1.0", "FriendlyName": "Olmuse Audio",
                 "Description": "Sounds made with Olmuse. Content only, no code modules.", "Category": "Audio", "CreatedBy": "Olmuse",
                 "CanContainContent": True, "IsBetaVersion": False, "Installed": False,
                 "Plugins": [{"Name": "PythonScriptPlugin", "Enabled": True, "TargetAllowList": ["Editor"]}, {"Name": "Metasound", "Enabled": True}]}


def test_sound_names_and_files():
    ids = ["amb_wind", "bgm.main", "sfx-hit", "한글소리", "a b", "a_b", "Kick", "kick", "k" * 70, "9start"]
    b = data({"assets": [asset(i) for i in ids], "dynamics": []})
    names = {s["id"]: s["asset"] for s in b["sounds"]}
    assert names["amb_wind"] == "amb_wind" and names["9start"] == "9start" and names["Kick"] == "Kick"
    for i in ("bgm.main", "sfx-hit", "한글소리", "a b"):
        assert names[i].startswith(run("out = U.slug(%s);" % json.dumps(i, ensure_ascii=False)) + "_") and len(names[i].split("_")[-1]) == 6
    assert names["kick"] != "kick" and names["kick"].lower() != names["Kick"].lower()
    assert names["a_b"] == "a_b" and names["a b"] != "a_b"
    assert len(names["k" * 70]) == 60 and names["k" * 70].startswith("k" * 53 + "_")
    assert len({n.lower() for n in names.values()}) == len(ids)
    assert all(s["file"] == "OlmuseAudio/audio/%s.wav" % s["id"] for s in b["sounds"])
    assert run("out = U.fnv('a');") == "e40c292c"   # FNV-1a 32-bit reference value


def test_dynamic_and_input_names():
    params = [{"id": "intensity", "name": "i"}, {"id": "강도", "name": "강도"}, {"id": "Intensity", "name": "I"}]
    b = data({"assets": [], "dynamics": [dyn_with([], params, id="dyn_1"), dyn_with([], [], id="숲.밤")]})
    d1, d2 = b["dynamics"]
    assert d1["asset"] == "MS_dyn_1" and d2["asset"].startswith("MS_x_")
    inputs = [p["input"] for p in d1["params"]]
    assert inputs[0] == "intensity"
    assert inputs[1].startswith("x_") and inputs[1] != "강도"
    assert inputs[2].lower() != "intensity" and inputs[2].startswith("Intensity_")


def test_loop_flag_is_the_sounds_own():
    b = data({"assets": [asset("drone", False)], "dynamics": [dyn_with([{"asset": "drone", "role": "bed"}])]})
    assert b["sounds"][0]["loop"] is False


def levels(on, param="x", volume=1):
    b = data({"assets": [asset("s")], "dynamics": [dyn_with([{"asset": "s", "role": "bed", "param": param, "on": on, "volume": volume}])]})
    return b["dynamics"][0]["layers"][0]


def test_level_numbers():
    l = levels([0.3, 0.8])
    assert (l["scale"], l["offset"]) == (2, -0.6)
    l = levels([0.8, 0.3])
    assert (l["scale"], l["offset"]) == (-2, 1.6)
    l = levels([0.5, 0.5])
    lvl = lambda p: max(0, min(1, p * l["scale"] + l["offset"]))
    assert lvl(0.5) == 1 and lvl(0.49) == 0       # a step, full from on[0] like the preview
    l = levels([0, 1], param=None)
    assert (l["param"], l["scale"], l["offset"]) == (None, 0, 1)
    l = levels([0, 1], param="nope")
    assert l["param"] is None and (l["scale"], l["offset"]) == (0, 1)
    assert levels([0, 1], volume=-0.5)["volume"] == 0 and levels([0, 1], volume=0.75)["volume"] == 0.75
    assert levels([0, 1/3])["scale"] == 3 and levels([0.1, 0.4])["offset"] == -0.333333


def test_roles_and_scatter_cleanup():
    layers = [{"asset": "s", "role": "weird"}, {"asset": "s", "role": "stem"},
              {"asset": "s", "role": "scatter"},
              {"asset": "s", "role": "scatter", "scatter": {"min_gap": 0.01, "max_gap": 0.001, "pitch": [2, 0.5], "pan": [3, -2]}},
              {"asset": "s", "role": "scatter", "scatter": {"min_gap": 5, "max_gap": 1}}]
    b = data({"assets": [asset("s")], "dynamics": [dyn_with(layers)]})
    ls = b["dynamics"][0]["layers"]
    assert [l["role"] for l in ls] == ["bed", "stem", "scatter", "scatter", "scatter"]
    assert "scatter" not in ls[0] and "scatter" not in ls[1]
    assert ls[2]["scatter"] == {"min_gap": 2, "max_gap": 8, "semitones": [0, 0], "pan": [0, 0]}
    assert ls[3]["scatter"] == {"min_gap": 0.05, "max_gap": 0.05, "semitones": [-12, 12], "pan": [-1, 1]}
    assert ls[4]["scatter"]["min_gap"] == 5 and ls[4]["scatter"]["max_gap"] == 5
    b = data(BASE)
    assert b["dynamics"][0]["layers"][2]["scatter"]["semitones"] == [-1.824037, 1.650042]


def test_fade_and_bar():
    b = data({"assets": [], "dynamics": [dyn_with([], id="a"), dyn_with([], id="m", type="music", bpm=90, beats_per_bar=3),
                                         dyn_with([], id="n", type="music"), dyn_with([], id="k", type="music", bpm=120, beats_per_bar=0)]})
    a, m, n, k = b["dynamics"]
    assert (a["type"], a["fade_seconds"], a["bar_seconds"]) == ("ambience", 0.8, None)
    assert (m["type"], m["fade_seconds"], m["bar_seconds"]) == ("music", 0.666667, 2)
    assert (n["fade_seconds"], n["bar_seconds"]) == (0.5, 2)       # bpm 120 when missing, 4 beats
    assert k["bar_seconds"] == 0.5                                  # at least one beat per bar


def test_skipped_layers():
    layers = [{"asset": "gone", "role": "bed"}] + [{"asset": "s", "role": "bed"}] * 10
    b = data({"assets": [asset("s")], "dynamics": [dyn_with(layers)]})
    d = b["dynamics"][0]
    assert len(d["layers"]) == 8
    assert d["skipped"] == [{"sound": "gone", "why": "not_approved"}, {"sound": "s", "why": "too_many_layers"}, {"sound": "s", "why": "too_many_layers"}]
    readme = bundle({"assets": [asset("s")], "dynamics": [dyn_with(layers)]})[3]["text"]
    assert "`gone`" in readme and "승인되지 않은 소리" in readme and "sound not approved" in readme


def test_items_without_id_are_left_out():
    b = data({"assets": [asset("s")], "dynamics": [{"name": "noid", "params": [], "layers": []},
                                                    dyn_with([], [{"name": "p"}, {"id": "q", "name": "q"}])]})
    assert [d["id"] for d in b["dynamics"]] == ["d"]
    assert [p["id"] for p in b["dynamics"][0]["params"]] == ["q"]
    readme = bundle({"assets": [asset("s")], "dynamics": [{"name": "noid", "params": [], "layers": []}]})[3]["text"]
    assert "`noid`" in readme


def test_no_dynamics_still_five_files():
    files = bundle({"game": "g", "assets": [asset("a")]})
    assert len(files) == 5 and json.loads(files[-1]["text"])["dynamics"] == []


def test_same_input_same_text_and_hash_per_dynamic():
    a, b = bundle(BASE), bundle(BASE)
    assert a == b and not any("\r" in f["text"] for f in a)
    two = json.loads(json.dumps(BASE))
    two["dynamics"].append(dict(json.loads(json.dumps(two["dynamics"][0])), id="dyn_2"))
    h1 = [d["hash"] for d in data(two)["dynamics"]]
    two["dynamics"][1]["layers"][0]["volume"] = 0.5
    h2 = [d["hash"] for d in data(two)["dynamics"]]
    assert h1[0] == h2[0] and h1[1] != h2[1] and len(h1[0]) == 8


def test_data_top_level():
    b = data(BASE)
    assert (b["olmuse_unreal"], b["game"], b["tested_engine"], b["content_root"]) == (1, "숲의 노래", "5.8", "/Game/Olmuse")
    assert b["dynamics"][0]["params"][0] == {"id": "intensity", "input": "intensity", "name": "강도", "min": 0, "max": 1, "default": 0.5}


def test_readme_lists_every_param_and_asset():
    project = json.loads(json.dumps(BASE))
    project["dynamics"][0]["params"].append({"id": "강도", "name": "세기", "min": 0, "max": 2, "default": 1})
    files = bundle(project)
    readme, b = files[3]["text"], json.loads(files[-1]["text"])
    for d in b["dynamics"]:
        assert "`%s`" % d["asset"] in readme
        for p in d["params"]:
            assert "`%s`" % p["input"] in readme
    for s in b["sounds"]:
        assert "`%s`" % s["asset"] in readme
    assert readme.index("## 한국어") < readme.index("## English")
    assert "Set Float Parameter" in readme and "OlmuseAudio.uplugin" in readme
