"""The board as records (board.js) under Node: the text form the server compares, the page's snapshot as records and back
onto the live objects, fitting a big sound record, the three-way merge of each row of the sync spec's G table, the
repairs that run after a merge, the untouched sample board, and the bytes a record points at."""
import json, pathlib, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"
FILES = ("data.js", "store.js", "board.js")

HELPERS = r"""
const B = window.assetBoard, S = window.assetStore;
// The live state of the page that board.patch works on, and app.js's snapshot() of it, line for line.
function model(over = {}) {
  const m = { assets: [], trash: [], cats: [], refs: [], dynamics: [], agentLog: [],
    vals: { game: 'Moon Farm', brief: 'calm', platform: 'mobile', loud: [-20, -14], demo: false, stage: 'sample',
      idRule: { pattern: '{kind}_{name}', sep: '_', prefix: { sfx: 'sfx', amb: 'amb', music: 'bgm' }, check: true },
      exportOpts: { format: 'wav', rate: 48000, bits: 16, quality: 'high', folders: 'flat', root: 'audio', engine: 'none' } }, ...over };
  m.get = (k) => m.vals[k];
  m.set = (k, v) => { m.vals[k] = v; };
  m.makeId = (name, cat, taken) => { const base = String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_') || cat; let id = base, k = 2; while (taken.has(id)) id = base + '_' + k++; taken.add(id); return id; };
  return m;
}
function keptOf(a, binned) {
  const kept = !binned && (a.status === 'review' || !!a.work);
  const status = (a.status === 'working' || a.status === 'review') && !kept ? (a.versions.length ? 'draft' : 'pending') : a.status;
  return { status, versions: a.versions, drafts: kept ? a.drafts : [], pick: kept ? a.pick : -1 };
}
function snap(m) {
  const one = (binned) => (a) => {
    const { versions, drafts: options, source, progress, ...rest } = a, kept = keptOf(a, binned);
    return { ...rest, key: a.key, status: kept.status, versions: kept.versions.map(S.record), drafts: kept.drafts.map(S.record), pick: kept.pick, hasSource: !!source };
  };
  const v = m.vals;
  return { v: S.SNAPSHOT, game: v.game, brief: v.brief, platform: v.platform, demo: v.demo, stage: v.stage, loud: [...v.loud], cats: m.cats, idRule: v.idRule, exportOpts: v.exportOpts,
    projectRefs: m.refs, agentLog: m.agentLog.slice(-30), trash: m.trash.map(one(true)), dynamics: m.dynamics.map((d) => ({ ...d, params: d.params.map((p) => ({ ...p })) })), assets: m.assets.map(one(false)) };
}
const recs = (m) => Object.fromEntries([...B.toRecords(snap(m))].map(([k, d]) => [k, B.canon(d)]));
const nk = (id, at, more = {}) => ({ id, at, note: null, engine: 'nkido', job: 'j' + id, parent: null, draft: null, source: 'SRC ' + id, seconds: 1, bpm: null, prompt: 'PROMPT ' + id, model: 'm', sources: [],
  measure: { peak: -6 }, issues: [], peaks: [0.1, 0.2], key: 'ver:' + id, stems: [], rate: 48000, channels: 1, bits: 16, bytes: 10, sha256: 'a'.repeat(63) + id.slice(-1), ...more });
const leg = (id, at) => ({ id, at, note: null, change: {}, engine: 'legacy', sources: [] });
const sound = (key, more = {}) => ({ key, id: 'sfx_' + key, name: 'Sound ' + key, cat: 'ui', music: false, loop: false, layers: [], status: 'draft', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0, ...more });
// A board with something of every kind: groups (one inside another, one with references), a project reference with a
// file, a dynamic sound with a slider moved, sounds under review, being made, approved, brought in, and in the trash.
function fullModel() {
  const m = model();
  m.cats.push({ id: 'ui', name: { en: 'UI', ko: 'UI' }, kind: 'sfx', hue: '#E8AE72' }, { id: 'bgm', name: { en: 'Music', ko: '음악' }, kind: 'music', hue: '#87B9E8', refs: [{ id: 'rc', kind: 'link', url: 'https://x.test' }] },
    { id: 'bgm_forest', name: '숲', kind: 'music', hue: '#8CCDB2', parent: 'bgm' });
  m.refs.push({ id: 'r1', kind: 'audio', name: 'ref.wav', key: 'ref:r1', note: '느낌', sha256: 'f'.repeat(64), bytes: 5 });
  m.dynamics.push({ id: 'dyn_ab12cd', name: 'Battle', type: 'music', bpm: 120, beats: 4, params: [{ id: 'tension', name: 'Tension', min: 0, max: 1, default: 0, value: 0.7 }], layers: [{ asset: 'sfx_a', role: 'bed', param: 'tension', on: [0, 1], gain: 1 }] });
  m.assets.push(
    sound('ka', { status: 'approved', versions: [nk('v1', 1000), nk('v2', 2000, { stems: [{ label: 'drums', key: 'ver:v2:s1', bytes: 4, sha256: 'b'.repeat(64) }] })], current: 1, chat: [{ me: true, text: '밝게' }],
      refs: [{ id: 'rp', kind: 'link', from: 'project' }, { id: 'ra', kind: 'text', note: 'own', from: 'asset' }], description: '버튼', when: 'click' }),
    sound('kb', { status: 'review', versions: [nk('v3', 3000)], drafts: [nk('d1', 4000, { draft: { k: 1, n: 2 } }), nk('d2', 4000, { draft: { k: 2, n: 2 } })], pick: 1 }),
    sound('kc', { status: 'working', versions: [], work: { request: 'req-1', kind: 'acct', who: 'w'.repeat(16), dev: 'd'.repeat(16), mode: 'make', text: '', n: 1, at: 5, before: 'pending', jobs: [{ id: 'job1', k: 1, got: false }] }, progress: 0.4 }),
    sound('s_ui_click', { sample: true, status: 'draft', versions: [leg('sv_s_ui_click', 7)] }),
    sound('kd', { imported: true, file: 'hit.wav', license: 'CC0-1.0', holder: 'Kim', guessed: true, autoCat: true, versions: [{ ...nk('v4', new Date(1700000000000)), engine: 'import', job: null }], source: new Float32Array(4) }),
  );
  m.trash.push(sound('ke', { trashedAt: 1700000005000, versions: [nk('v5', 6000)] }));
  m.agentLog.push({ me: true, text: 'device only' });
  return m;
}
"""


def node(script):
    out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr[-3000:]
    return json.loads(out.stdout)


def run(body):
    src = "globalThis.window = globalThis;\n" + "\n".join((ROOT / f).read_text(encoding="utf-8") for f in FILES) + HELPERS
    return node(src + "\n(async () => {\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });")


def test_canon_is_the_servers_json_dumps_with_sorted_keys():
    got = run(r"""
    const x = { b: 1, a: [3, { z: '한글', y: 0.5, w: -0 }, null], c: 'é🎵', d: undefined, e: 1e21, f: NaN, g: 'x\ud800y', h: true };
    out.text = B.canon(x); out.bytes = B.utf8(out.text);
    """)
    value = json.loads(got["text"])
    # the same bytes as the server's canonical form of the same value (Korean, a pair, numbers)
    assert got["text"] == json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert got["bytes"] == len(got["text"].encode("utf-8"))
    assert value["g"] == "x�y" and value["f"] is None and "d" not in value


def test_records_patched_onto_an_empty_page_make_the_same_records_and_patching_again_changes_nothing():
    got = run(r"""
    const m = fullModel(), before = recs(m);
    out.keys = Object.keys(before).sort();
    const asset = JSON.parse(before['asset/ka']), work = JSON.parse(before['asset/kc']), bin = JSON.parse(before['asset/ke']);
    out.assetFields = Object.keys(asset).sort();
    out.cur = asset.cur; out.ownRefs = asset.refs.map((r) => r.id); out.at = JSON.parse(before['asset/kd']).versions[0].at;
    out.work = work.work; out.trashed = [bin.trashedAt, asset.trashedAt];
    out.dyn = JSON.parse(before['dyn/dyn_ab12cd']).params;
    out.reviewDrafts = JSON.parse(before['asset/kb']).drafts.map((v) => v.id);
    // onto an empty page
    const e = model({ vals: { ...model().vals, game: '', demo: true } });
    for (const [k, d] of B.toRecords(snap(m))) { const i = k.indexOf('/'); B.patch(e, k.slice(0, i), k.slice(i + 1), d); }
    const after = recs(e);
    out.same = JSON.stringify(after) === JSON.stringify(before);
    out.diff = Object.keys(before).filter((k) => before[k] !== after[k]);
    out.lists = [e.assets.map((a) => a.key), e.trash.map((a) => a.key), e.cats.map((c) => c.id)];
    out.picked = [e.assets[0].current, e.assets[1].pick, e.dynamics[0].params[0].value, 'agentLog' in e.assets[0]];
    // onto the page it came from: nothing changes and every object is still the one it was
    const objs = [...m.assets, ...m.trash, ...m.cats, ...m.refs, ...m.dynamics, ...m.assets.flatMap((a) => [...a.versions, ...a.drafts, a.versions, a.drafts, a.chat])];
    const loud = m.vals.loud, idRule = m.vals.idRule;
    let changed = 0;
    for (const [k, d] of B.toRecords(snap(m))) { const i = k.indexOf('/'); if (B.patch(m, k.slice(0, i), k.slice(i + 1), d)) changed++; }
    const objs2 = [...m.assets, ...m.trash, ...m.cats, ...m.refs, ...m.dynamics, ...m.assets.flatMap((a) => [...a.versions, ...a.drafts, a.versions, a.drafts, a.chat])];
    out.identity = [changed, objs.length === objs2.length && objs.every((o, i) => o === objs2[i]), m.vals.loud === loud, m.vals.idRule === idRule, m.assets[2].work.jobs[0].got === false, m.assets[2].progress];
    // a change from elsewhere lands on the same objects
    const a = m.assets[0], v1 = a.versions[0], d = JSON.parse(before['asset/ka']);
    d.name = 'Renamed'; d.versions.push({ ...d.versions[0], id: 'v9', key: 'ver:v9', at: 9000 }); d.cur = 'v9';
    out.landed = [B.patch(m, 'asset', 'ka', d) === a, a.name, a.versions[0] === v1, a.versions.length, a.current, m.assets[0] === a];
    // moved to the trash and back, then deleted
    d.trashedAt = 5; B.patch(m, 'asset', 'ka', d);
    out.binned = [m.assets.includes(a), m.trash.includes(a), a.trashedAt];
    d.trashedAt = null; B.patch(m, 'asset', 'ka', d);
    out.back = [m.assets.includes(a), 'trashedAt' in a];
    B.patch(m, 'asset', 'ka', null); B.patch(m, 'cat', 'bgm_forest', null);
    out.removed = [m.assets.includes(a), m.cats.map((c) => c.id)];
    """)
    assert got["keys"] == ["asset/ka", "asset/kb", "asset/kc", "asset/kd", "asset/ke", "asset/s_ui_click", "cat/bgm", "cat/bgm_forest", "cat/ui", "dyn/dyn_ab12cd", "meta/game", "meta/rules", "ref/r1"]
    assert got["cur"] == "v2" and got["ownRefs"] == ["ra"] and got["at"] == 1700000000000
    assert got["work"]["dev"] == "d" * 16 and got["work"]["jobs"] == [{"id": "job1", "k": 1}]  # got is this computer's
    assert got["trashed"] == [1700000005000, None]
    assert got["dyn"] == [{"default": 0, "id": "tension", "max": 1, "min": 0, "name": "Tension"}]  # the slider stays here
    assert got["reviewDrafts"] == ["d1", "d2"]
    for device in ("progress", "source", "hasSource", "current", "pick", "key"):
        assert device not in got["assetFields"], device
    assert got["same"], got["diff"]
    assert got["lists"] == [["ka", "kb", "kc", "s_ui_click", "kd"], ["ke"], ["ui", "bgm", "bgm_forest"]]
    assert got["picked"] == [1, 0, 0, False]
    assert got["identity"] == [0, True, True, True, True, 0.4]
    assert got["landed"] == [True, "Renamed", True, 3, 2, True]
    assert got["binned"] == [False, True, 5] and got["back"] == [True, False]
    assert got["removed"] == [False, ["ui", "bgm"]]


def test_every_field_of_the_sample_board_and_of_a_new_slot_is_shared_or_kept_on_the_device():
    got = run(r"""
    const m = model();
    m.assets = window.STUDIO_DATA.ASSETS.map((d) => ({ ...d, key: 's_' + d.id, status: d.sample ? 'draft' : 'pending', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0 }));
    // what app.js's blank() and intake() put on a sound
    m.assets.push(sound('kx', { imported: true, file: 'a.wav', license: '', holder: '', guessed: true, autoCat: true, when: '', description: '', ref: 's_ui_click', tempo: 100, length: 2, prompt: 'p' }));
    out.none = B.strays(snap(m));
    m.assets[0].colour = 'red'; m.trash.push(sound('ky', { trashedAt: 1, mood: 'x' }));
    out.some = B.strays(snap(m));
    """)
    assert got["none"] == []
    assert got["some"] == ["colour", "mood"]


def test_fit_cuts_old_prompts_then_old_patches_the_same_way_every_time_and_keeps_the_one_in_use():
    got = run(r"""
    const big = (n) => 'x'.repeat(n);
    const versions = [nk('v1', 3000, { prompt: big(300000), source: big(300000) }), nk('v2', 1000, { prompt: big(300000), source: big(300000) }), nk('v3', 2000, { prompt: big(300000), source: big(300000) })];
    const a = sound('ka', { versions, current: 1 }), m = model(); m.assets.push(a);
    const one = B.toRecords(snap(m)).get('asset/ka'), two = B.toRecords(snap(m)).get('asset/ka');
    out.same = B.canon(one) === B.canon(two);
    out.size = [B.sizeOf(one) <= B.FIT_MAX, B.sizeOf(one) > B.FIT_MAX - 400000];
    out.kept = one.versions.map((v) => [v.id, 'prompt' in v, 'source' in v]);
    out.untouched = versions.every((v) => v.prompt.length === 300000);
    const small = B.toRecords(snap(model({ assets: [sound('kb', { versions: [nk('v1', 1)] })] }))).get('asset/kb');
    out.small = small.versions[0].prompt;
    // the receiving page keeps the version objects it has, with their full prompt
    B.patch(m, 'asset', 'ka', one);
    out.receiver = [m.assets[0].versions[1] === versions[1], m.assets[0].versions[0].prompt.length];
    """)
    assert got["same"] and got["size"] == [True, True]
    # v2 (1000) is the one in use; the oldest other (v3, 2000) loses its prompt first, then v1 (3000), then v3's patch
    assert got["kept"] == [["v1", False, True], ["v2", True, True], ["v3", False, False]]
    assert got["untouched"] and got["small"] == "PROMPT v1" and got["receiver"] == [True, 300000]


def test_merge3_follows_each_row_of_the_table():
    got = run(r"""
    const M = (kind, b, m, t, w = false) => B.merge3(kind, b, m, t, w);
    const game = { game: 'Moon', brief: 'calm', platform: 'mobile', loud: [-20, -14], demo: true, stage: 'sample' };
    const r = {};
    let x = M('meta', game, { ...game, game: 'Sun' }, { ...game, brief: 'loud' });
    r.gameBoth = [x.data.game, x.data.brief, x.lost];
    x = M('meta', game, { ...game, game: 'Sun' }, { ...game, game: 'Star' });
    r.gameFirst = [x.data.game, x.lost];
    x = M('meta', game, { ...game, game: 'Sun' }, { ...game, game: 'Star' }, true);
    r.gameMine = [x.data.game, x.lost];
    x = M('meta', game, { ...game, demo: false }, { ...game, stage: 'make' });
    const y = M('meta', { ...game, demo: false }, { ...game, demo: true }, { ...game, demo: false });
    r.demo = [x.data.demo, x.data.stage, y.data.demo, y.lost];
    const rules = { idRule: { pattern: '{name}', sep: '_' }, exportOpts: { format: 'wav' } };
    x = M('meta', rules, { ...rules, idRule: { pattern: '{name}', sep: '-' } }, { ...rules, idRule: { pattern: '{kind}_{name}', sep: '_' }, exportOpts: { format: 'ogg' } });
    r.rules = [x.data.idRule, x.data.exportOpts, x.lost];
    const cat = { id: 'forest', name: 'Forest', kind: 'amb', hue: '#1', refs: [{ id: 'a' }] };
    x = M('cat', cat, { ...cat, name: '숲' }, { ...cat, hue: '#2', refs: [{ id: 'a' }, { id: 'b' }] });
    r.cat = [x.data.name, x.data.hue, x.data.refs.length, x.lost];
    x = M('cat', null, { id: 'forest', name: 'Forest', kind: 'amb', hue: '#1' }, { id: 'forest', name: 'Forest', kind: 'amb', hue: '#3' });
    r.catTwice = [x.data.hue, x.data.name];
    const ref = { id: 'r1', kind: 'text', note: 'a' };
    x = M('ref', ref, { ...ref, note: 'mine' }, { ...ref, note: 'theirs' });
    r.ref = [x.data.note, x.lost];
    const dyn = { id: 'dyn_a', name: 'D', params: [{ id: 'p', min: 0 }], layers: [{ asset: 'x' }] };
    x = M('dyn', dyn, { ...dyn, params: [{ id: 'p', min: 1 }], name: 'E' }, { ...dyn, params: [{ id: 'p', min: 0 }, { id: 'q' }] });
    r.dyn = [x.data.params.length, x.data.name, x.lost];
    // sounds
    const base = { id: 'sfx_a', name: 'A', cat: 'ui', loop: false, status: 'draft', cur: 'v1', work: null, versions: [{ id: 'v1', at: 1 }], drafts: [], chat: [{ me: true, text: 'hi' }], refs: [{ id: 'ra', note: 'x', from: 'asset' }], trashedAt: null };
    x = M('asset', base, { ...base, name: 'B' }, { ...base, loop: true });
    r.fields = [x.data.name, x.data.loop, x.lost];
    x = M('asset', base, { ...base, name: 'B' }, { ...base, name: 'C' });
    r.sameField = [x.data.name, x.lost];
    x = M('asset', base, { ...base, versions: [...base.versions, { id: 'm1', at: 3 }] }, { ...base, versions: [...base.versions, { id: 't1', at: 2 }] });
    r.versions = x.data.versions.map((v) => v.id);
    x = M('asset', base, { ...base, versions: [] }, base);
    r.neverFewer = x.data.versions.map((v) => v.id);
    x = M('asset', base, { ...base, status: 'approved' }, { ...base, versions: [...base.versions, { id: 'v2', at: 2 }], cur: 'v2' });
    r.bundle = [x.data.status, x.data.cur, x.lost];
    x = M('asset', base, { ...base, status: 'approved' }, { ...base, versions: [...base.versions, { id: 'v2', at: 2 }], cur: 'v2' }, true);
    r.bundleMine = [x.data.status, x.data.cur, x.lost];
    const review = { ...base, status: 'review', drafts: [{ id: 'd1', at: 5 }, { id: 'd2', at: 5 }] };
    // one side adopts (the drafts become versions), the other throws them away
    x = M('asset', review, { ...review, status: 'draft', drafts: [], versions: [...base.versions, { id: 'd1', at: 5 }, { id: 'd2', at: 5 }], cur: 'd2' }, { ...review, status: 'draft', drafts: [] });
    r.adoptVsDiscard = [x.data.versions.map((v) => v.id), x.data.drafts.length, x.data.status, x.data.cur, x.lost];
    x = M('asset', review, { ...review, status: 'draft', drafts: [] }, { ...review, status: 'draft', drafts: [], versions: [...base.versions, { id: 'd1', at: 5 }, { id: 'd2', at: 5 }], cur: 'd1' });
    r.discardVsAdopt = [x.data.versions.map((v) => v.id), x.data.drafts.length, x.data.status, x.data.cur];
    x = M('asset', base, { ...base, trashedAt: 9 }, { ...base, description: 'new' });
    r.trashAndEdit = [x.data.trashedAt, x.data.description];
    x = M('asset', base, { ...base, chat: [...base.chat, { me: true, text: 'mine' }] }, { ...base, chat: [...base.chat, { me: false, text: 'theirs' }] });
    r.chat = x.data.chat.map((c) => c.text);
    x = M('asset', base, { ...base, refs: [{ id: 'ra', note: 'm', from: 'asset' }, { id: 'rb', from: 'asset' }] }, { ...base, refs: [{ id: 'ra', note: 't', from: 'asset' }, { id: 'rc', from: 'asset' }] });
    r.refs = [x.data.refs.map((q) => q.id + ':' + (q.note || '')), x.lost];
    x = M('asset', base, { ...base, refs: [] }, base);
    r.refDropped = x.data.refs.length;
    // deletes (cat, ref, dyn and a sound's purge) against edits, both orders, and the record's first maker
    x = M('cat', cat, null, { ...cat, name: 'Renamed' });
    r.editFirst = [x.data && x.data.name, x.lost, x.gone];
    x = M('cat', cat, { ...cat, name: 'Renamed' }, null);
    r.deleteFirst = [x.data, x.lost, x.gone];
    x = M('cat', cat, cat, null);
    r.deleteQuiet = [x.data, x.gone];
    x = M('cat', cat, null, cat);
    r.myDelete = x.data;
    x = M('cat', null, { ...cat, name: 'Again' }, null);
    r.maker = x.data && x.data.name;
    x = M('asset', { ...base, trashedAt: 3 }, { ...base, trashedAt: null }, null);
    r.staleCannotRevive = [x.data, x.gone];
    x = M('asset', { ...base, trashedAt: 3 }, null, { ...base, trashedAt: null });
    r.purgeAfterRestore = [x.data && x.data.trashedAt, x.lost];
    x = M('cat', cat, null, { ...cat, name: 'Renamed' }, true);
    r.ownDelete = x.data;
    out.r = r;
    """)
    r = got["r"]
    assert r["gameBoth"] == ["Sun", "loud", False]
    assert r["gameFirst"] == ["Star", True] and r["gameMine"] == ["Sun", False]
    assert r["demo"] == [False, "make", False, False]  # once false, false
    assert r["rules"] == [{"pattern": "{kind}_{name}", "sep": "_"}, {"format": "ogg"}, True]  # each rule whole
    assert r["cat"] == ["숲", "#2", 2, False] and r["catTwice"] == ["#3", "Forest"]
    assert r["ref"] == ["theirs", True]
    assert r["dyn"] == [2, "E", True]  # params whole: theirs, name mine
    assert r["fields"] == ["B", True, False] and r["sameField"] == ["C", True]
    assert r["versions"] == ["v1", "t1", "m1"] and r["neverFewer"] == ["v1"]
    assert r["bundle"] == ["draft", "v2", True] and r["bundleMine"] == ["approved", "v1", False]
    assert r["adoptVsDiscard"] == [["v1", "d1", "d2"], 0, "draft", "v1", True]
    assert r["discardVsAdopt"] == [["v1", "d1", "d2"], 0, "draft", "d1"]
    assert r["trashAndEdit"] == [9, "new"]
    assert r["chat"] == ["hi", "theirs", "mine"]
    assert r["refs"] == [["ra:t", "rc:", "rb:"], True] and r["refDropped"] == 0
    assert r["editFirst"] == ["Renamed", True, False] and r["deleteFirst"] == [None, False, True] and r["deleteQuiet"] == [None, False]
    assert r["myDelete"] is None and r["maker"] == "Again"
    assert r["staleCannotRevive"] == [None, True] and r["purgeAfterRestore"] == [None, True]
    assert r["ownDelete"] is None


def test_sane_makes_status_and_the_version_in_use_agree_with_the_lists():
    got = run(r"""
    const s = (d) => { const x = B.sane(structuredClone(d)); return [x.status, x.cur]; };
    out.r = [
      s({ status: 'draft', cur: 'gone', versions: [{ id: 'a', at: 1 }, { id: 'b', at: 5 }, { id: 'c', at: 3 }], drafts: [] }),
      s({ status: 'review', cur: null, versions: [{ id: 'a', at: 1 }], drafts: [] }),
      s({ status: 'review', cur: null, versions: [], drafts: [] }),
      s({ status: 'approved', cur: 'a', versions: [{ id: 'a', at: 1 }], drafts: [{ id: 'd' }] }),
      s({ status: 'working', cur: 'a', versions: [{ id: 'a', at: 1 }], drafts: [{ id: 'd' }] }),
      s({ status: 'pending', cur: null, versions: [{ id: 'a', at: 1 }], drafts: [] }),
      s({ status: 'pending', cur: null, versions: [], drafts: [] }),
    ];
    """)
    assert got["r"] == [["draft", "b"], ["draft", "a"], ["pending", None], ["review", "a"], ["working", "a"], ["draft", "a"], ["pending", None]]


def test_fix_ids_gives_the_same_names_on_two_computers_whatever_order_they_hold_the_sounds_in():
    got = run(r"""
    const shadow = { 'asset/k1': { rev: 7, born: 7 }, 'asset/k2': { rev: 9, born: 3 }, 'asset/k3': { rev: 4, born: 4 } };
    const mk = (keys) => { const m = model(); m.assets = keys.map((k) => sound(k, { id: 'sfx_door', name: 'Door' })); m.assets.push(sound('k4', { id: 'sfx_door_2', name: 'Door' })); return m; };
    const a = mk(['k1', 'k2', 'k3', 'k9']), b = mk(['k9', 'k3', 'k1', 'k2']);
    out.changed = B.fixIds(a, shadow).map((x) => x.key);
    B.fixIds(b, shadow);
    const ids = (m) => Object.fromEntries(m.assets.map((x) => [x.key, x.id]));
    out.a = ids(a); out.b = ids(b);
    out.again = B.fixIds(a, shadow).length;
    // the trash is not looked at
    const c = model(); c.assets = [sound('k1', { id: 'x' })]; c.trash = [sound('k2', { id: 'x', trashedAt: 1 })];
    out.trash = B.fixIds(c, {}).length;
    """)
    assert got["a"] == got["b"]
    assert got["a"]["k2"] == "sfx_door"  # born first on the server
    assert sorted(got["a"].values()) == sorted(set(got["a"].values()))  # no two alike
    assert got["a"]["k9"] not in ("sfx_door",) and got["changed"] == ["k3", "k1", "k9"]  # not on the server yet: last
    assert got["again"] == 0 and got["trash"] == 0


def test_revert_fields_only_takes_back_what_still_holds_the_answers_value():
    got = run(r"""
    out.r = B.revertFields({ name: 'Old', cat: 'ui', description: '' }, { name: 'New', cat: 'combat', description: 'loud' }, { name: 'New', cat: 'env', description: 'loud' });
    out.gone = B.revertFields({ when: undefined }, { when: 'x' }, { when: 'x' });
    """)
    assert got["r"] == {"name": "Old", "description": ""}  # cat was changed by someone since: it stays
    assert got["gone"] == {}  or got["gone"] == {"when": None}


def test_pristine_is_only_the_untouched_sample_board():
    got = run(r"""
    const base = () => { const m = model(); m.vals.demo = true; m.assets = [sound('s_a', { sample: true, versions: [leg('sv_s_a', 1)] }), sound('s_b', { sample: true, status: 'pending' })]; return m; };
    const p = (fn) => { const m = base(); fn(m); return B.pristine(snap(m)); };
    out.r = [p(() => {}), p((m) => { m.vals.demo = false; }), p((m) => { m.trash.push(sound('s_c', { sample: true, trashedAt: 1 })); }), p((m) => { m.refs.push({ id: 'r' }); }),
      p((m) => { m.dynamics.push({ id: 'dyn_x', params: [] }); }), p((m) => { m.assets.push(sound('k1')); }), p((m) => { m.assets[0].versions.push(nk('v1', 2)); }),
      p((m) => { m.assets[0].work = { request: 'r', jobs: [] }; m.assets[0].status = 'working'; }), p((m) => { m.assets[0].name = 'Renamed'; }),
      p((m) => { m.assets.push(sound('s_slot')); }), p((m) => { m.assets.push(sound('s_slot', { versions: [nk('v2', 2)] })); })];
    """)
    # renaming a sample keeps the board a sample board (clearBoard's own check is the record against the module's);
    # the page's own empty stand-in slots (s_ keys, no sample flag) belong to the sample board, until one is made
    assert got["r"] == [True, False, False, False, False, False, False, False, True, True, False]


def test_shas_of_a_record_in_upload_order_and_the_keys_the_server_holds():
    got = run(r"""
    const m = fullModel(), r = B.toRecords(snap(m));
    out.ka = B.shasOf('asset', r.get('asset/ka')).map((x) => [x.key, x.rank, x.job, x.stem, !!x.sha]);
    out.kb = B.shasOf('asset', r.get('asset/kb')).map((x) => [x.key, x.rank]);
    out.legacy = B.shasOf('asset', r.get('asset/s_ui_click'));
    out.ref = B.shasOf('ref', r.get('ref/r1')).map((x) => [x.key, x.sha.length, x.size]);
    const shadow = {};
    for (const [k, d] of r) shadow[k] = { rev: 1, born: 1, dev: 'x', json: B.canon(d) };
    shadow['asset/kz'] = { rev: 2, born: 2, dev: 'x', gone: true, json: B.canon({ versions: [nk('vz', 1)] }) };
    out.remote = [...B.remoteKeys({ shadow })].sort();
    out.none = B.remoteKeys(null).size;
    """)
    assert got["ka"] == [["ver:v2", 0, "jv2", None, True], ["ver:v1", 2, "jv1", None, True], ["ver:v2:s1", 3, "jv2", 1, True]]
    assert got["kb"] == [["ver:v3", 0], ["ver:d1", 1], ["ver:d2", 1]]
    assert got["legacy"] == [] and got["ref"] == [["ref:r1", 64, 5]]
    assert got["remote"] == ["ref:r1", "ver:d1", "ver:d2", "ver:v1", "ver:v2", "ver:v2:s1", "ver:v3", "ver:v4", "ver:v5"]  # not the gone one, not legacy
    assert got["none"] == 0
