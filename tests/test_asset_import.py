"""Bringing existing work into the asset board: name guessing, pasted lists, the bundle zip, and reference measurements."""
import json, pathlib, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"


def run(body):
    src = "globalThis.window = globalThis;\n" + "\n".join((ROOT / f).read_text(encoding="utf-8") for f in ("data.js", "synth.js", "importer.js", "measure.js", "store.js"))
    script = src + "\n(async () => {\n" + body + "\n})().catch((e) => { console.error(e); process.exit(1); });"
    out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", check=True)  # stdin: Windows caps a command line at 32K
    return json.loads(out.stdout)


def test_category_and_name_come_from_file_and_folder_names():
    got = run("""
    const g = (p, s = 0.3) => [importer.guessCategory(p, s).cat, importer.guessName(p)];
    console.log(JSON.stringify({
      swing: g('Sword_Swing_01.wav'), click: g('UI/btn_press.ogg'), amb: g('amb_forest_night.wav', 8),
      bgm: g('Main Theme.mp3', 90), korean: g('효과음/발소리_흙.wav'), unknown: g('thing.wav', 0.2), longUnknown: g('thing2.wav', 40),
      camel: g('playerJumpLand.wav'),
    }));""")
    assert got["swing"] == ["combat", "Sword swing 01"]
    assert got["click"][0] == "ui"  # the folder says so
    assert got["amb"] == ["env", "Forest night"]
    assert got["bgm"][0] == "bgm"
    assert got["korean"][0] == "char"
    assert got["unknown"][0] == "ui" and got["longUnknown"][0] == "bgm"
    assert got["camel"] == ["char", "Player jump land"]


def test_ids_follow_the_naming_rule_and_never_collide():
    got = run("""
    const taken = new Set(['sfx_hit']);
    console.log(JSON.stringify([importer.makeId('Hit', 'combat', taken), importer.makeId('Hit', 'combat', taken), importer.makeId('바람', 'env', taken), importer.makeId('Main theme', 'bgm', taken)]));""")
    assert got == ["sfx_hit_2", "sfx_hit_3", "amb_env", "bgm_main_theme"]


def test_pasted_lists_with_and_without_a_header():
    got = run("""
    const plain = importer.parseList('- Button click\\n2. Sword hit, combat, short and dry\\nbgm_title\\n숲, 환경\\n\\n');
    const csv = importer.parseList('id,name,category,when,description,length\\nsfx_coin,Coin,ui,Picking up a coin,"bright, short",0.4\\n,Boss roar,combat,,,');
    console.log(JSON.stringify({ plain, csv }));""")
    plain, csv = got["plain"], got["csv"]
    assert [x["name"] for x in plain] == ["Button click", "Sword hit", "Title", "숲"]
    assert [x["cat"] for x in plain] == ["ui", "combat", "bgm", "env"]
    assert plain[1]["description"] == "short and dry"
    assert plain[2]["id"] == "bgm_title" and plain[3]["loop"] is True
    assert csv[0] == {"id": "sfx_coin", "name": "Coin", "cat": "ui", "when": "Picking up a coin", "description": "bright, short", "length": 0.4, "loop": False}
    assert csv[1]["name"] == "Boss roar" and csv[1]["id"] is None


def test_bundle_zip_round_trips_and_deflated_zips_open():
    got = run("""
    const wav = importer.encodeWav(new Float32Array([0, 0.5, -0.5, 1]), 22050);
    const blob = importer.zip([{ path: 'game-audio.spec.json', bytes: new TextEncoder().encode('{"assets":[]}') }, { path: 'audio/sfx_a.wav', bytes: wav }]);
    const back = await importer.unzip(await blob.arrayBuffer());
    // A zip made by another tool, deflated: build one by hand with CompressionStream.
    const raw = new TextEncoder().encode('hello hello hello hello');
    const packed = new Uint8Array(await new Response(new Blob([raw]).stream().pipeThrough(new CompressionStream('deflate-raw'))).arrayBuffer());
    const stored = new Uint8Array(await importer.zip([{ path: 'x.txt', bytes: packed }]).arrayBuffer());
    const v = new DataView(stored.buffer), end = stored.length - 22, dir = v.getUint32(end + 16, true);
    v.setUint16(8, 8, true); v.setUint32(22, raw.length, true); v.setUint16(dir + 10, 8, true); v.setUint32(dir + 24, raw.length, true);
    const deflated = await importer.unzip(stored.buffer);
    console.log(JSON.stringify({ paths: back.map((f) => f.path), wavSame: back[1].bytes.join() === wav.join(), riff: new TextDecoder().decode(back[1].bytes.slice(0, 4)), text: new TextDecoder().decode(deflated[0].bytes) }));""")
    assert got == {"paths": ["game-audio.spec.json", "audio/sfx_a.wav"], "wavSame": True, "riff": "RIFF", "text": "hello hello hello hello"}


def test_brought_in_sounds_render_and_carry_band_measurements():
    got = run("""
    const rate = 22050, low = new Float32Array(rate / 2), high = new Float32Array(rate / 2);
    for (let i = 0; i < low.length; i++) { low[i] = 0.5 * Math.sin(2 * Math.PI * 80 * i / rate); high[i] = 0.5 * Math.sin(2 * Math.PI * 7000 * i / rate); }
    const m = (src, change) => synth.measure(synth.render({ source: src, layers: [] }, change));
    const a = m(low), b = m(high), faster = m(low, { shift: 2, stretch: 1 });
    // Whether a sound's record passes the licence rule, judged as the room judges it: the one table (assetMeasure.lint)
    // over the sources the room records for that sound (assetStore.sourcesFor).
    const lic = (asset) => !assetMeasure.lint({ kind: 'sfx', id: 'sfx_a', sources: assetStore.sourcesFor(asset) }, a).some((i) => i.id === 'lic');
    console.log(JSON.stringify({ a, b, faster, licEmpty: lic({ imported: true, license: '' }), licSet: lic({ imported: true, license: 'CC0' }), licMade: lic({}),
      rule: assetMeasure.RULES.filter((r) => r.id === 'lic').map((r) => [r.level, !!r.text]), old: 'RULES' in window.STUDIO_DATA }));""")
    assert got["a"]["low"] > 80 and got["b"]["high"] > got["a"]["high"] + 30 and got["b"]["low"] < 10
    assert 60 < got["a"]["bright"] < 100 and got["b"]["bright"] > 5000
    assert abs(got["a"]["seconds"] - 0.5) < 0.01 and abs(got["faster"]["seconds"] - 0.25) < 0.01
    assert got["licEmpty"] is False and got["licSet"] is True and got["licMade"] is True
    assert got["rule"] == [["error", True]] and got["old"] is False  # one table judges; the sample data carries none of its own


def test_exported_zip_names_are_marked_utf8_and_carry_the_unicode_path_field():
    import base64, io, zipfile
    got = run("""
    const blob = importer.zip([{ path: 'audio/발소리.wav', bytes: new Uint8Array([1, 2, 3]) }, { path: 'CREDITS.md', bytes: new Uint8Array([4]) }]);
    console.log(JSON.stringify(Buffer.from(await blob.arrayBuffer()).toString('base64')));""")
    raw = base64.b64decode(got)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        assert [i.filename for i in infos] == ["audio/발소리.wav", "CREDITS.md"]
        assert all(i.flag_bits & 0x800 for i in infos)
        assert infos[0].extra[:2] == b"\x75\x70" and infos[0].extra[9:].decode() == "audio/발소리.wav"
        assert infos[1].extra == b""  # plain ASCII names need no extra field
        assert z.read("audio/발소리.wav") == b"\x01\x02\x03"


def test_cp949_zip_names_from_windows_explorer_are_read_as_korean():
    got = run("""
    // A zip made with an ASCII name of the same byte length, then the name swapped for its CP949 bytes and the flag cleared.
    const cp949 = new Uint8Array([0xb9, 0xdf, 0xbc, 0xd2, 0xb8, 0xae]); // 발소리
    const bytes = new Uint8Array(await importer.zip([{ path: 'xxxxxx.wav', bytes: new Uint8Array([9]) }]).arrayBuffer());
    for (let i = 0; i + 6 <= bytes.length; i++) if (String.fromCharCode(...bytes.slice(i, i + 6)) === 'xxxxxx') bytes.set(cp949, i);
    const v = new DataView(bytes.buffer), end = bytes.length - 22, dir = v.getUint32(end + 16, true);
    v.setUint16(6, 0, true); v.setUint16(dir + 8, 0, true);
    const back = await importer.unzip(bytes.buffer);
    console.log(JSON.stringify({ path: back[0].path, guess: importer.guessCategory(back[0].path, 0.2).cat }));""")
    assert got == {"path": "발소리.wav", "guess": "char"}


def test_unzip_skips_entries_over_the_size_limit_and_junk_is_recognised():
    got = run("""
    const blob = importer.zip([{ path: 'small.wav', bytes: new Uint8Array(10) }, { path: 'huge.wav', bytes: new Uint8Array(5000) }]);
    const back = await importer.unzip(await blob.arrayBuffer(), 1000);
    console.log(JSON.stringify({ kept: back.map((f) => [f.path, f.size]), skipped: back.skipped,
      junk: ['__MACOSX/x/._a.wav', 'sfx/._a.wav', 'Thumbs.db', '.DS_Store', 'sfx/a.wav'].map(importer.junk), limits: importer.LIMITS }))""")
    assert got["kept"] == [["small.wav", 10]] and got["skipped"] == [{"path": "huge.wav", "why": "big"}]
    assert got["junk"] == [True, True, True, True, False]
    assert got["limits"]["file"] == 50 * 1024 * 1024
