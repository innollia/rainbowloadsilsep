"""The two Python files of the Unreal bundle (unreal_py.js), taken out with Node and run here on a small stand-in for
Unreal's `unreal` module: the pre-check, what a second run skips, a changed or missing WAV, failures in the middle, the
trial build that guards an existing MetaSound, the files written whatever happens, and the editor-start watch
(docs/ASSET_UNREAL_SPEC.md D, E, F)."""
import importlib, json, os, pathlib, py_compile, subprocess, sys, types

import pytest

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"


def py_texts():
    src = "globalThis.window = globalThis;\n" + (ROOT / "unreal_py.js").read_text(encoding="utf-8") + \
        "\nprocess.stdout.write(JSON.stringify(window.unrealPy));\n"
    out = subprocess.run(["node", "-"], input=src, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    return json.loads(out.stdout)


TEXTS = py_texts()


# ---------------- a stand-in for the parts of `unreal` the scripts use ----------------

class R:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "MetaSoundBuilderResult." + self.name


R.SUCCEEDED, R.FAILED = R("SUCCEEDED"), R("FAILED")


class Props:
    def __init__(self, **kw):
        self.p = dict(kw)

    def set_editor_property(self, k, v):
        self.p[k] = v

    def get_editor_property(self, k):
        return self.p.get(k)


class NodeHandle:
    def __init__(self, i=None):
        self.i = i

    def export_text(self):
        return "(NodeID=%s)" % self.i

    def import_text(self, t):
        self.i = int(t.split("=")[1].rstrip(")"))

    def __eq__(self, o):
        return isinstance(o, NodeHandle) and o.i == self.i

    def __hash__(self):
        return hash(self.i)


class OutH:
    def __init__(self, node, pin):
        self.node, self.pin = node, pin


class InH(OutH):
    pass


class Builder:
    def __init__(self, fake, name):
        self.fake, self.name = fake, name
        self.nodes, self.inputs, self.links, self.defaults = set(), {}, [], {}

    def _r(self, what):
        self.fake.calls.append(("builder", self.name, what))
        return R.FAILED if what in self.fake.fail_builder else R.SUCCEEDED

    def add_node_by_class_name(self, cn, major):
        key = "|".join(cn.p[k] for k in ("namespace", "name", "variant"))
        if key in self.fake.missing_nodes:
            return NodeHandle(), R.FAILED
        self.fake.seq += 1
        h = NodeHandle(self.fake.seq)
        self.nodes.add(h)
        return h, self._r("add " + key)

    def find_node_input_by_name(self, n, pin):
        return InH(n, pin), R.SUCCEEDED

    def find_node_output_by_name(self, n, pin):
        return OutH(n, pin), R.SUCCEEDED

    def connect_nodes(self, o, i):
        self.links.append((o, i))
        return self._r("connect " + i.pin)

    def set_node_input_default(self, i, lit):
        self.defaults[(i.node.i if isinstance(i.node, NodeHandle) else i.node, i.pin)] = lit
        return self._r("default " + i.pin)

    def add_graph_input_node(self, name, typ, lit):
        self.inputs[name] = lit
        return OutH("input", name), self._r("input " + name)

    def get_graph_input_names(self):
        return ["UE.Source.OnPlay"] + list(self.inputs), R.SUCCEEDED

    def remove_graph_input(self, name):
        self.inputs.pop(name, None)
        return self._r("remove input")

    def contains_node(self, h):
        return h in self.nodes

    def remove_node(self, h):
        self.nodes.discard(h)
        return self._r("remove node")

    def find_graph_input_node(self, name):
        return name, "Trigger", OutH("graph", name), R.SUCCEEDED

    def find_graph_output_node(self, name):
        return name, "Audio", InH("graph", name), R.SUCCEEDED


class Asset(Props):
    def __init__(self, path, cls, **kw):
        super().__init__(**kw)
        self.path, self.cls, self.meta, self.builder = path, cls, {}, None

    def get_outermost(self):
        return types.SimpleNamespace(get_name=lambda: self.path)


class Fake(types.ModuleType):
    def __init__(self, root):
        super().__init__("unreal")
        self.root = root
        self.assets, self.disk, self.calls, self.logs = {}, {}, [], []
        self.seq = 0
        self.fail_builder, self.missing_nodes, self.empty_import, self.dirty = set(), set(), set(), set()
        self.version = "5.8.4-58902052+++UE5+Release-5.8"
        self.command_line = "Check.uproject -nosplash"
        self.pie = False
        self.ticks = []
        fake = self
        self.MetaSoundBuilderResult = R
        self.MetaSoundNodeHandle = NodeHandle
        self.MetaSoundBuilderNodeOutputHandle = OutH
        self.MetaSoundBuilderNodeInputHandle = InH
        self.MetasoundFrontendClassName = Props
        self.MetaSoundOutputAudioFormat = types.SimpleNamespace(STEREO="STEREO")
        self.AssetImportTask = Props
        self.LevelEditorSubsystem = "LevelEditorSubsystem"
        self.MetaSoundBuilderSubsystem = "MetaSoundBuilderSubsystem"
        self.MetaSoundEditorSubsystem = "MetaSoundEditorSubsystem"
        self.SystemLibrary = types.SimpleNamespace(get_engine_version=lambda: fake.version, get_command_line=lambda: fake.command_line,
                                                   quit_editor=lambda: fake.calls.append(("quit",)))
        self.Paths = types.SimpleNamespace(project_dir=lambda: str(root), convert_relative_path_to_full=lambda p: p)
        self.AssetRegistryHelpers = types.SimpleNamespace(get_asset_registry=lambda: types.SimpleNamespace(
            scan_paths_synchronous=lambda paths, force: fake.calls.append(("scan",))))
        self.AssetToolsHelpers = types.SimpleNamespace(get_asset_tools=lambda: types.SimpleNamespace(import_asset_tasks=fake._import))
        self.EditorAssetLibrary = types.SimpleNamespace(
            does_asset_exist=lambda p: p in fake.assets, load_asset=lambda p: fake.assets.get(p.split(".")[0]),
            save_loaded_asset=fake._save_loaded, save_asset=fake._save_asset,
            set_metadata_tag=lambda a, k, v: a.meta.__setitem__(k, v), get_metadata_tag=lambda a, k: a.meta.get(k, ""),
            delete_asset=lambda p: fake.calls.append(("delete_asset", p)))
        self.EditorLoadingAndSavingUtils = types.SimpleNamespace(
            get_dirty_content_packages=lambda: [types.SimpleNamespace(get_name=lambda p=p: p) for p in fake.dirty],
            reload_packages=lambda pkgs: fake.calls.append(("reload",)))
        self.bsub = types.SimpleNamespace(
            create_source_builder=fake._create_builder, unregister_source_builder=lambda n: fake.calls.append(("unregister", n)),
            create_float_meta_sound_literal=lambda v: (("f", v), "Float"), create_bool_meta_sound_literal=lambda v: (("b", v), "Bool"),
            create_object_meta_sound_literal=lambda o: ("o", o.path))
        self.esub = types.SimpleNamespace(build_to_asset=fake._build_to_asset, find_or_begin_building=fake._find_or_begin)

    # engine pieces
    def get_engine_subsystem(self, cls):
        return self.bsub

    def get_editor_subsystem(self, cls):
        if cls == "LevelEditorSubsystem":
            return types.SimpleNamespace(is_in_play_in_editor=lambda: self.pie)
        return self.esub

    def log(self, m):
        self.logs.append(m)

    log_warning = log_error = log

    def register_slate_post_tick_callback(self, fn):
        self.ticks.append(fn)
        return len(self.ticks)

    def unregister_slate_post_tick_callback(self, h):
        pass

    def _import(self, tasks):
        self.calls.append(("import", [t.p["destination_name"] for t in tasks]))
        for t in tasks:
            name, data = t.p["destination_name"], open(t.p["filename"], "rb").read()
            if not data.startswith(b"RIFF") or name in self.empty_import:
                t.p["imported_object_paths"] = []
                continue
            path = t.p["destination_path"] + "/" + name
            self.assets[path] = Asset(path, "SoundWave", looping=False, data=data)   # a replacing import starts with looping off
            self.disk[path] = data
            t.p["imported_object_paths"] = ["%s.%s" % (path, name)]

    def _save_loaded(self, a, only_dirty):
        self.calls.append(("save", a.path))
        self.disk[a.path] = dict(a.p, meta=dict(a.meta))
        return True

    def _save_asset(self, path, only_dirty):
        self.calls.append(("save", path))
        a = self.assets[path]
        self.disk[path] = {"meta": dict(a.meta), "nodes": set(a.builder.nodes), "inputs": dict(a.builder.inputs)}
        return True

    def _create_builder(self, name, fmt, one_shot):
        self.calls.append(("create_builder", name))
        b = Builder(self, name)
        return b, OutH("graph", "OnPlay"), InH("graph", "OnFinished"), [InH("graph", "L"), InH("graph", "R")], R.SUCCEEDED

    def _build_to_asset(self, builder, author, name, dest, _):
        path = dest + "/" + name
        self.calls.append(("build_to_asset", path))
        if path in self.assets:
            return None, R.FAILED
        a = Asset(path, "MetaSoundSource")
        a.builder = builder
        builder.name = path
        self.assets[path] = a
        return a, R.SUCCEEDED

    def _find_or_begin(self, ms):
        self.calls.append(("find_or_begin_building", ms.path))
        return ms.builder, R.SUCCEEDED

    def count(self, kind):
        return len([c for c in self.calls if c[0] == kind])


# ---------------- a project on disk ----------------

def wav(seconds=1.0):
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(b"\0\0" * int(48000 * seconds))
    return buf.getvalue()


MANIFEST = {
    "olmuse_unreal": 1, "game": "g", "tested_engine": "5.8", "content_root": "/Game/Olmuse",
    "sounds": [{"id": "amb_wind", "name": "바람", "file": "OlmuseAudio/audio/amb_wind.wav", "asset": "amb_wind", "loop": True},
               {"id": "sfx.bird", "name": "새", "file": "OlmuseAudio/audio/sfx.bird.wav", "asset": "sfx_bird_95c051", "loop": False},
               {"id": "amb_rain", "name": "비", "file": "OlmuseAudio/audio/amb_rain.wav", "asset": "amb_rain", "loop": True}],
    "dynamics": [
        {"id": "dyn_1", "name": "숲", "asset": "MS_dyn_1", "type": "ambience",
         "params": [{"id": "intensity", "input": "intensity", "name": "강도", "min": 0, "max": 1, "default": 0.5}],
         "fade_seconds": 0.8, "bar_seconds": None,
         "layers": [{"sound": "amb_wind", "role": "bed", "param": None, "scale": 0, "offset": 1, "volume": 1},
                    {"sound": "amb_rain", "role": "bed", "param": "intensity", "scale": 2, "offset": -0.6, "volume": 1},
                    {"sound": "sfx.bird", "role": "scatter", "param": "intensity", "scale": 1, "offset": 0, "volume": 1,
                     "scatter": {"min_gap": 2, "max_gap": 8, "semitones": [-1.8, 1.6], "pan": [-0.8, 0.8]}}],
         "skipped": [], "hash": "aaaa0001"},
        {"id": "dyn_2", "name": "음악", "asset": "MS_dyn_2", "type": "music",
         "params": [{"id": "긴장", "input": "x_1234ab", "name": "긴장", "min": 0, "max": 1, "default": 0}],
         "fade_seconds": 0.5, "bar_seconds": 2,
         "layers": [{"sound": "amb_wind", "role": "stem", "param": None, "scale": 0, "offset": 1, "volume": 1},
                    {"sound": "amb_rain", "role": "stem", "param": "긴장", "scale": 1, "offset": 0, "volume": 1}],
         "skipped": [], "hash": "bbbb0001"}],
}


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    py = root / "Plugins/OlmuseAudio/Content/Python"
    py.mkdir(parents=True)
    (py / "init_unreal.py").write_text(TEXTS["INIT"], encoding="utf-8")
    (py / "olmuse_unreal.py").write_text(TEXTS["IMPORTER"], encoding="utf-8")
    (root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8")
    audio = root / "OlmuseAudio/audio"
    audio.mkdir(parents=True)
    for s in MANIFEST["sounds"]:
        (root / s["file"]).write_bytes(wav())
    fake = Fake(root)
    monkeypatch.setitem(sys.modules, "unreal", fake)
    monkeypatch.syspath_prepend(str(py))
    sys.modules.pop("olmuse_unreal", None)
    sys.modules.pop("init_unreal", None)
    mod = importlib.import_module("olmuse_unreal")
    yield types.SimpleNamespace(root=root, fake=fake, mod=mod, py=py)
    sys.modules.pop("olmuse_unreal", None)
    sys.modules.pop("init_unreal", None)


def record(p):
    return json.loads((p.root / "Plugins/OlmuseAudio/imported.json").read_text(encoding="utf-8"))


def result(p):
    return json.loads((p.root / "Saved/Olmuse/last_import.json").read_text(encoding="utf-8"))


# ---------------- tests ----------------

def test_both_files_compile(tmp_path):
    for name, text in (("init_unreal.py", TEXTS["INIT"]), ("olmuse_unreal.py", TEXTS["IMPORTER"])):
        f = tmp_path / name
        f.write_text(text, encoding="utf-8")
        py_compile.compile(str(f), cfile=str(tmp_path / (name + "c")), doraise=True)
        assert "sys.dont_write_bytecode = True" in text.split("import unreal")[0]


def test_first_run_imports_and_builds(proj):
    r = proj.mod.run(str(proj.root))
    f = proj.fake
    assert r["ok"] and sorted(r["sounds"]["imported"]) == ["amb_rain", "amb_wind", "sfx.bird"]
    assert r["dynamics"]["built"] == ["dyn_1", "dyn_2"]
    assert f.count("import") == 1                                       # one import call for all sounds
    assert f.assets["/Game/Olmuse/Audio/amb_wind"].p["looping"] is True and f.assets["/Game/Olmuse/Audio/sfx_bird_95c051"].p["looping"] is False
    assert f.assets["/Game/Olmuse/Audio/sfx_bird_95c051"].meta == {"OlmuseId": "sfx.bird", "OlmuseName": "새"}
    ms = f.assets["/Game/Olmuse/Dynamic/MS_dyn_2"]
    assert set(ms.builder.inputs) == {"x_1234ab"} and ms.meta["OlmuseInputs"] == "x_1234ab" and ms.meta["OlmuseNodes"]
    assert ("save", "/Game/Olmuse/Dynamic/MS_dyn_1") in f.calls
    rec = record(proj)
    assert set(rec["sounds"]) == {"amb_wind", "sfx.bird", "amb_rain"} and rec["dynamics"]["dyn_1"]["hash"] == "aaaa0001"
    assert result(proj)["ok"] is True
    assert any(m.startswith("Olmuse: 소리 3개 가져옴") for m in f.logs) and any(m.startswith("Olmuse: imported 3") for m in f.logs)


def test_second_run_does_nothing(proj):
    proj.mod.run(str(proj.root))
    f = proj.fake
    f.calls.clear()
    r = proj.mod.run(str(proj.root))
    assert f.count("import") == 0 and f.count("build_to_asset") == 0 and f.count("find_or_begin_building") == 0 and f.count("save") == 0
    assert sorted(r["sounds"]["unchanged"]) == ["amb_rain", "amb_wind", "sfx.bird"] and r["dynamics"]["unchanged"] == ["dyn_1", "dyn_2"]


def test_changed_wav_alone_is_imported_again_and_looping_set_again(proj):
    proj.mod.run(str(proj.root))
    f = proj.fake
    f.calls.clear()
    (proj.root / "OlmuseAudio/audio/amb_wind.wav").write_bytes(wav(2.0))
    r = proj.mod.run(str(proj.root))
    assert [c[1] for c in f.calls if c[0] == "import"] == [["amb_wind"]]
    assert f.assets["/Game/Olmuse/Audio/amb_wind"].p["looping"] is True and f.disk["/Game/Olmuse/Audio/amb_wind"]["looping"] is True
    assert r["dynamics"]["unchanged"] == ["dyn_1", "dyn_2"]               # the MetaSounds keep pointing at the same path


def test_missing_file(proj):
    (proj.root / "OlmuseAudio/audio/amb_rain.wav").unlink()
    r = proj.mod.run(str(proj.root))
    assert r["sounds"]["missing"] == ["amb_rain"] and "amb_rain" not in record(proj)["sounds"]
    left = {x["id"]: x["layers"] for x in r["dynamics"]["layers_left_out"]}
    assert left["dyn_1"] == [{"sound": "amb_rain", "why": "sound_missing"}]


def test_rebuild_edits_the_asset_in_place(proj):
    proj.mod.run(str(proj.root))
    f = proj.fake
    ms = f.assets["/Game/Olmuse/Dynamic/MS_dyn_1"]
    n_before = len(ms.builder.nodes)
    m = json.loads(json.dumps(MANIFEST, ensure_ascii=False))
    m["dynamics"][0]["layers"][0]["volume"] = 0.5
    m["dynamics"][0]["hash"] = "aaaa0002"
    (proj.root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    f.calls.clear()
    r = proj.mod.run(str(proj.root))
    assert r["dynamics"]["updated"] == ["dyn_1"] and r["dynamics"]["unchanged"] == ["dyn_2"]
    assert f.count("build_to_asset") == 0 and f.count("delete_asset") == 0
    assert f.assets["/Game/Olmuse/Dynamic/MS_dyn_1"] is ms and len(ms.builder.nodes) == n_before
    assert record(proj)["dynamics"]["dyn_1"]["hash"] == "aaaa0002"


def test_precheck_without_import_names_changes_nothing(proj):
    del proj.fake.AssetImportTask
    r = proj.mod.run(str(proj.root))
    assert proj.fake.count("import") == 0 and proj.fake.count("build_to_asset") == 0 and not proj.fake.assets
    assert any("소리를 가져올 수 없어 아무것도 바꾸지 않았습니다" in m and "AssetImportTask" in m for m in proj.fake.logs)
    assert any(m.startswith("Olmuse: this Unreal version") for m in proj.fake.logs)
    assert result(proj)["ok"] is False


def test_precheck_without_a_node_imports_sounds_only(proj):
    proj.fake.missing_nodes.add("UE|InterpTo|Audio")
    proj.fake.version = "5.9.0-1+++UE5+Release-5.9"
    r = proj.mod.run(str(proj.root))
    assert len(r["sounds"]["imported"]) == 3 and proj.fake.count("build_to_asset") == 0
    assert any("5.9.0" in m and "동적 소리를 만들 수 없어 소리 파일만 가져왔습니다" in m and "InterpTo" in m for m in proj.fake.logs)


def test_major_version_warning_only(proj):
    proj.fake.version = "6.0.0-1+++UE6"
    r = proj.mod.run(str(proj.root))
    assert r["ok"] and any("시험한 Unreal은 5.8" in m for m in proj.fake.logs)


def test_one_sound_failing_keeps_the_rest(proj):
    f = proj.fake
    f.empty_import.add("amb_rain")
    r = proj.mod.run(str(proj.root))
    assert [x["id"] for x in r["sounds"]["failed"]] == ["amb_rain"] and sorted(r["sounds"]["imported"]) == ["amb_wind", "sfx.bird"]
    assert "amb_rain" not in record(proj)["sounds"] and "amb_wind" in record(proj)["sounds"]
    assert any("소리 1개를 가져오지 못했습니다(amb_rain" in m for m in f.logs)
    f.empty_import.clear()
    f.calls.clear()
    r = proj.mod.run(str(proj.root))
    assert [c[1] for c in f.calls if c[0] == "import"] == [["amb_rain"]]
    assert r["dynamics"]["updated"] == ["dyn_1", "dyn_2"]          # a sound that now exists is wired in


def test_not_a_wav_is_named(proj):
    m = json.loads(json.dumps(MANIFEST, ensure_ascii=False))
    m["sounds"][2]["file"] = "OlmuseAudio/audio/amb_rain.ogg"
    (proj.root / "OlmuseAudio/audio/amb_rain.ogg").write_bytes(b"OggS....")
    (proj.root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    r = proj.mod.run(str(proj.root))
    assert r["sounds"]["failed"] == [{"id": "amb_rain", "why": "format_not_imported"}]


def test_failed_trial_build_leaves_the_asset_alone(proj):
    proj.mod.run(str(proj.root))
    f = proj.fake
    m = json.loads(json.dumps(MANIFEST, ensure_ascii=False))
    m["dynamics"][0]["hash"] = "aaaa0003"
    (proj.root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    saved = f.disk["/Game/Olmuse/Dynamic/MS_dyn_1"]
    f.fail_builder.add("connect Pitch Shift")
    f.calls.clear()
    r = proj.mod.run(str(proj.root))
    assert [x["id"] for x in r["dynamics"]["failed"]] == ["dyn_1"] and "connect pitch" in r["dynamics"]["failed"][0]["why"]
    assert ("find_or_begin_building", "/Game/Olmuse/Dynamic/MS_dyn_1") not in f.calls
    assert ("save", "/Game/Olmuse/Dynamic/MS_dyn_1") not in f.calls and f.disk["/Game/Olmuse/Dynamic/MS_dyn_1"] is saved
    assert record(proj)["dynamics"]["dyn_1"]["hash"] == "aaaa0001"
    assert ("unregister", "OlmuseTrial_MS_dyn_1_0") in f.calls


def test_failed_edit_in_place_is_reverted_and_not_saved(proj):
    proj.mod.run(str(proj.root))
    f = proj.fake
    m = json.loads(json.dumps(MANIFEST, ensure_ascii=False))
    m["dynamics"][0]["hash"] = "aaaa0005"
    (proj.root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    f.fail_builder.add("remove input")                                  # the trial passes, the edit on the asset breaks
    f.calls.clear()
    r = proj.mod.run(str(proj.root))
    assert [x["id"] for x in r["dynamics"]["failed"]] == ["dyn_1"]
    assert ("find_or_begin_building", "/Game/Olmuse/Dynamic/MS_dyn_1") in f.calls
    assert f.count("reload") == 1 and ("save", "/Game/Olmuse/Dynamic/MS_dyn_1") not in f.calls
    assert record(proj)["dynamics"]["dyn_1"]["hash"] == "aaaa0001"


def test_failed_first_build_makes_no_asset(proj):
    proj.fake.fail_builder.add("connect Pitch Shift")
    r = proj.mod.run(str(proj.root))
    assert [x["id"] for x in r["dynamics"]["failed"]] == ["dyn_1"] and r["dynamics"]["built"] == ["dyn_2"]
    assert "/Game/Olmuse/Dynamic/MS_dyn_1" not in proj.fake.assets and "dyn_1" not in record(proj)["dynamics"]


def test_unsaved_edits_are_not_overwritten(proj):
    proj.mod.run(str(proj.root))
    m = json.loads(json.dumps(MANIFEST, ensure_ascii=False))
    m["dynamics"][0]["hash"] = "aaaa0004"
    (proj.root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    proj.fake.dirty.add("/Game/Olmuse/Dynamic/MS_dyn_1")
    r = proj.mod.run(str(proj.root))
    assert r["dynamics"]["skipped"] == [{"id": "dyn_1", "why": "unsaved_edits"}]
    assert record(proj)["dynamics"]["dyn_1"]["hash"] == "aaaa0001"


def test_files_are_written_when_the_run_breaks(proj, monkeypatch):
    real = proj.mod.say

    def boom(key, **kw):
        if key == "done":
            raise RuntimeError("boom")
        return real(key, **kw)
    monkeypatch.setattr(proj.mod, "say", boom)
    r = proj.mod.run(str(proj.root))
    assert "boom" in r["error"] and result(proj)["ok"] is False and "boom" in result(proj)["error"]
    assert set(record(proj)["sounds"]) == {"amb_wind", "sfx.bird", "amb_rain"}


def test_music_graph_holds_values_to_the_bar_and_scatter_has_no_loop(proj):
    proj.mod.run(str(proj.root))
    f = proj.fake
    music = f.assets["/Game/Olmuse/Dynamic/MS_dyn_2"].builder
    adds = [c[2] for c in f.calls if c[0] == "builder" and c[1].startswith("OlmuseTrial_MS_dyn_2_") and c[2].startswith("add ")]
    assert "add UE|TriggerRepeat|" in adds and "add Value|Value|Float" in adds
    assert ((music.defaults.get(next(k for k in music.defaults if k[1] == "Period")))) == ("f", 2.0)
    amb = [c[2] for c in f.calls if c[0] == "builder" and c[1].startswith("OlmuseTrial_MS_dyn_1_") and c[2].startswith("add ")]
    assert amb.count("add UE|Wave Player|Mono") == 1 and amb.count("add UE|Wave Player|Stereo") == 2
    assert "add Value|Value|Float" not in amb
    # no node feeds itself through a loop (the builder accepts a loop, so the importer must not make one)
    b = f.assets["/Game/Olmuse/Dynamic/MS_dyn_1"].builder
    edges = {}
    for o, i in b.links:
        if isinstance(o.node, NodeHandle) and isinstance(i.node, NodeHandle):
            edges.setdefault(o.node.i, set()).add(i.node.i)
    state = {}

    def visit(n):
        assert state.get(n) != "open", "loop through node %s" % n
        if state.get(n) == "done":
            return
        state[n] = "open"
        for m in edges.get(n, ()):
            visit(m)
        state[n] = "done"
    for n in list(edges):
        visit(n)
    assert len(edges) > 10


# ---------------- the editor-start watch ----------------

def start_watch(proj, monkeypatch, stub=True):
    if stub:
        (proj.py / "olmuse_unreal.py").write_text(
            "import os, unreal\n"
            "def run(root):\n"
            "    n = os.path.join(root, 'calls.txt')\n"
            "    open(n, 'a').write('x')\n"
            "    raise RuntimeError('broken import')\n", encoding="utf-8")
        sys.modules.pop("olmuse_unreal", None)
    clock = [1000.0]
    monkeypatch.setattr("time.time", lambda: clock[0])
    init = importlib.import_module("init_unreal")
    return init, clock


def ticks(proj, clock, seconds, step=0.25):
    end = clock[0] + seconds
    while clock[0] < end:
        clock[0] += step
        for fn in proj.fake.ticks:
            fn(step)


def calls(proj):
    p = proj.root / "calls.txt"
    return len(p.read_text()) if p.exists() else 0


def test_watch_tries_a_failing_file_once(proj, monkeypatch):
    init, clock = start_watch(proj, monkeypatch)
    assert len(proj.fake.ticks) == 1
    ticks(proj, clock, 10)
    assert calls(proj) == 1                                         # first tick imports, the failure is not retried
    assert result(proj)["ok"] is False and "broken import" in result(proj)["error"]
    assert any("가져오다가 멈췄습니다" in m for m in proj.fake.logs)
    ticks(proj, clock, 20)
    assert calls(proj) == 1
    (proj.root / "Plugins/OlmuseAudio/olmuse_build.json").write_text(json.dumps(MANIFEST) + " ", encoding="utf-8")
    ticks(proj, clock, 1)
    assert calls(proj) == 1                                         # waits for the file to settle
    ticks(proj, clock, 5)
    assert calls(proj) == 2


def test_watch_waits_for_play_in_editor(proj, monkeypatch):
    proj.fake.pie = True
    init, clock = start_watch(proj, monkeypatch)
    ticks(proj, clock, 10)
    assert calls(proj) == 0
    proj.fake.pie = False
    ticks(proj, clock, 3)
    assert calls(proj) == 1


def test_watch_runs_the_real_importer_and_quits_when_asked(proj, monkeypatch):
    monkeypatch.setenv("OLMUSE_QUIT_AFTER", "1")
    init, clock = start_watch(proj, monkeypatch, stub=False)
    ticks(proj, clock, 3)
    assert result(proj)["ok"] is True and proj.fake.count("quit") == 1
    assert (proj.root / "Saved/Olmuse/watch_run_1.json").exists()


def test_nothing_in_a_commandlet(proj, monkeypatch):
    proj.fake.command_line = "Check.uproject -run=pythonscript -script=x.py"
    init, clock = start_watch(proj, monkeypatch)
    assert proj.fake.ticks == []
