"""The asset board's storage (store.js) under Node, with an in-memory IndexedDB and Web Locks handed in: upgrading a board
saved before version records, the split writes, the three-way restore, versions whose sound is gone, the tab lock and guard,
and turning stored bytes back into sound. Also importer.encodeWav with more than one channel."""
import json, pathlib, re, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"
FILES = ("data.js", "synth.js", "importer.js", "measure.js", "store.js")
RECORD = ["at", "bits", "bpm", "bytes", "channels", "draft", "engine", "id", "issues", "job", "key", "measure", "model", "note", "parent", "peaks",
          "prompt", "rate", "seconds", "sha256", "source", "sources", "stems"]
# The project has not stated a licence or a holder for its own synth, so the entry carries neither.
SYNTH = {"name": "olmuse built-in synth", "license": "", "holder": "", "use": "Built-in synthesizer"}

HELPERS = r"""
const S = window.assetStore, M = window.assetMeasure, clock = { t: 1700000000000 };
const settle = (ms = 5) => new Promise((ok) => setTimeout(ok, ms));
const tone = (n, hz = 440, rate = 48000, amp = 0.5) => Float32Array.from({ length: n }, (_, i) => amp * Math.sin(2 * Math.PI * hz * i / rate));
const wav = (chans, rate = 48000, bits = 16) => importer.encodeWav(chans, rate, bits);
const counts = (list) => list.map((a) => [a.id, a.versions.length, (a.drafts || []).length]);
const quota = () => Object.assign(new Error('The quota has been exceeded.'), { name: 'QuotaExceededError' });

// IndexedDB in memory. A transaction runs its requests one macrotask after it was opened, in the order asked (a request
// made inside a success handler joins the line), and its writes land together when it completes, or not at all.
//   fail.put(store, key, value) / fail.get(store, key) / fail.open(name): return an Error to make that request fail.
//   fail.commit(stores, ops): return an Error to abort at commit (how a full disk often shows up).
//   bare: a failed request aborts the transaction without setting transaction.error (the error only bubbles as an event).
//   never: open() never answers.   log: every transaction that wrote, in order.   reads: every get, as 'store/key'.
function fakeIdb() {
  const stores = new Map(), log = [], reads = [];
  const fake = { stores, log, reads, fail: {}, bare: false, never: false };
  const keep = (v) => (v instanceof Blob ? v : structuredClone(v));
  const fire = (fn, arg) => { if (typeof fn === 'function') fn(arg); };
  function transaction(names, mode = 'readonly') {
    names = [].concat(names);
    for (const n of names) if (!stores.has(n)) throw new Error('NotFoundError: ' + n);
    const q = { error: null, mode, onerror: null, onabort: null, oncomplete: null }, todo = [], ops = [];
    let over = false;
    const ask = (run) => {
      if (over) throw new Error('TransactionInactiveError');
      const r = { result: undefined, error: null, onsuccess: null, onerror: null };
      todo.push({ r, run });
      return r;
    };
    q.objectStore = (name) => {
      if (!names.includes(name)) throw new Error('NotFoundError: ' + name);
      const real = stores.get(name);
      // A transaction reads back what it has itself written so far.
      const seen = (key) => {
        for (let i = ops.length - 1; i >= 0; i--) {
          const o = ops[i];
          if (o.store !== name) continue;
          if (o.op === 'clear') return [true, undefined];
          if (o.key === key) return [true, o.op === 'put' ? o.value : undefined];
        }
        return [false];
      };
      const read = (key) => { const [hit, v] = seen(key); return hit ? v : real.get(key); };
      const write = (op) => { if (mode !== 'readwrite') throw new Error('ReadOnlyError'); ops.push({ ...op, store: name }); };
      return {
        put: (value, key) => ask(() => { const e = fake.fail.put && fake.fail.put(name, key, value); if (e) throw e; write({ op: 'put', key, value: keep(value) }); return key; }),
        delete: (key) => ask(() => { write({ op: 'delete', key }); }),
        clear: () => ask(() => { write({ op: 'clear' }); }),
        get: (key) => ask(() => { reads.push(name + '/' + key); const e = fake.fail.get && fake.fail.get(name, key); if (e) throw e; const v = read(key); return v === undefined ? undefined : keep(v); }),
        getKey: (key) => ask(() => (read(key) === undefined ? undefined : key)),
        getAllKeys: () => ask(() => [...real.keys()].sort()),
      };
    };
    setTimeout(() => {
      while (todo.length) {
        const { r, run } = todo.shift();
        try { r.result = run(); }
        catch (e) {
          r.error = e; over = true;
          fire(r.onerror, { target: r });
          fire(q.onerror, { target: r }); // a request error bubbles to its transaction, which then aborts
          q.error = fake.bare ? null : e;
          fire(q.onabort, { target: q });
          return;
        }
        fire(r.onsuccess, { target: r });
      }
      over = true;
      const e = ops.length && fake.fail.commit && fake.fail.commit(names, ops);
      if (e) { q.error = e; fire(q.onabort, { target: q }); return; }
      for (const o of ops) { const s = stores.get(o.store); if (o.op === 'put') s.set(o.key, o.value); else if (o.op === 'delete') s.delete(o.key); else s.clear(); }
      if (ops.length) log.push({ stores: names, ops: ops.map((o) => o.op + ' ' + o.store + (o.key === undefined ? '' : '/' + o.key)) });
      fire(q.oncomplete, { target: q });
    }, 0);
    return q;
  }
  fake.indexedDB = {
    open(name, version) {
      const r = { result: null, error: null, onsuccess: null, onerror: null, onupgradeneeded: null, onblocked: null };
      if (fake.never) return r;
      setTimeout(() => {
        const e = fake.fail.open && fake.fail.open(name);
        if (e) { r.error = e; fire(r.onerror, { target: r }); return; }
        r.result = { name, version, createObjectStore: (n) => { stores.set(n, new Map()); }, transaction };
        if (!stores.size) fire(r.onupgradeneeded, { target: r });
        fire(r.onsuccess, { target: r });
      }, 0);
      return r;
    },
  };
  // Seeding and looking, outside any transaction.
  fake.seed = (board = {}, audio = {}) => { stores.set('board', new Map(Object.entries(board).map(([k, v]) => [k, keep(v)]))); stores.set('audio', new Map(Object.entries(audio))); };
  fake.board = (key = 'board') => stores.get('board')?.get(key);
  fake.audioKeys = () => [...(stores.get('audio')?.keys() || [])].sort();
  fake.disk = () => JSON.stringify([[...(stores.get('board') || [])], fake.audioKeys()]);
  return fake;
}

// navigator.locks for one name. The tab that has the lock keeps it until release() (that tab going away).
function fakeLocks() {
  let held = null;
  const line = [];
  const give = (cb) => { held = {}; Promise.resolve().then(() => cb({ name: 'lock' })); };
  return {
    request(name, a, b) {
      const opts = typeof a === 'function' ? {} : a, cb = typeof a === 'function' ? a : b;
      if (held && opts.ifAvailable) return Promise.resolve().then(() => cb(null));
      if (held) line.push(cb); else give(cb);
      return new Promise(() => {});
    },
    release() { held = null; const cb = line.shift(); if (cb) give(cb); },
    get waiting() { return line.length; },
  };
}

// The part of app.js that the store talks to: the lists, the snapshot, what a read record becomes, and the keys in use.
function page(fake, locks, extra = {}) {
  const p = { assets: [], trash: [], refs: new Map(), game: 'Sample board', notes: [], took: [], info: null, applied: 0, decoded: 0 };
  const pack = (a) => { const { versions, drafts, source, ...rest } = a; return { ...rest, versions: versions.map(S.record), drafts: (drafts || []).map(S.record), hasSource: !!source }; };
  p.snapshot = () => ({ v: S.SNAPSHOT, game: p.game, assets: p.assets.map(pack), trash: p.trash.map(pack) });
  p.keys = () => {
    const want = new Map();
    for (const a of [...p.assets, ...p.trash]) {
      if (a.source) want.set(a.key, () => new Blob([a.source]));
      for (const v of [...a.versions, ...(a.drafts || [])]) for (const k of S.versionKeys(v)) want.set(k, null);
    }
    for (const [k, bytes] of p.refs) want.set(k, () => new Blob([bytes]));
    return want;
  };
  p.apply = (data, buffers, info) => {
    const open = (x) => { const { hasSource, ...a } = x; if (hasSource && buffers.has(a.key)) a.source = new Float32Array(buffers.get(a.key)); return a; };
    const assets = data.assets.map(open), trash = (data.trash || []).map(open);
    p.refs = new Map([...buffers].filter(([k]) => k.startsWith('ref:')).map(([k, b]) => [k, new Uint8Array(b)]));
    p.game = data.game; p.assets = assets; p.trash = trash; p.info = info; p.applied++;
  };
  p.store = S.create({
    indexedDB: fake.indexedDB, locks, now: () => (clock.t += 1000), random: () => 0.5,
    snapshot: () => p.snapshot(), apply: (...x) => p.apply(...x), keys: () => p.keys(), assets: () => p.assets,
    notify: (what, n) => p.notes.push(n === undefined ? what : what + ' ' + n), onLock: (r) => p.took.push(r),
    // Stands in for the browser's decoder: 48 kHz, one channel made of the first bytes; too short a file is not sound.
    decode: async (u8) => { p.decoded++; if (u8.length < 8) throw new Error('unknown format'); return { rate: 48000, bits: null, chans: [Float32Array.from(u8.subarray(0, 8), (b) => b / 256)] }; },
    ...extra,
  });
  return p;
}
const open = async (fake, locks, extra) => { const p = page(fake, locks, extra); p.got = await p.store.lock(); p.result = await p.store.restore(); return p; };

// A version as the generation backend hands it over: measured on the server, its sound under ver: keys.
const nkido = (id, extra = {}) => ({
  id, at: 5000, note: null, engine: 'nkido', job: id, parent: null, draft: null, source: 'master((s) -> limiter(s, -1.5, 0.1))', seconds: 0.01, bpm: null, prompt: 'a soft click', model: 'm',
  sources: [{ name: 'nkido (Akkado, Cedar)', license: 'MIT', holder: 'Moritz Laass', use: 'Sound synthesis engine' }],
  measure: { peak: -6, loud: -20, seconds: 0.01 }, issues: [], peaks: Array(200).fill(0.25),
  key: 'ver:' + id, stems: [], rate: 48000, channels: 2, bits: 16, bytes: 0, sha256: null, ...extra,
});
const legacy = (id, at) => ({ id, at, note: null, change: {}, engine: 'legacy', sources: [] });
const row = (id, more = {}) => ({ id, name: id, cat: 'ui', status: 'draft', current: 0, pick: -1, chat: [], versions: [], drafts: [], ...more });

// A board the way the page saved it before version records: recipes for versions, a Float32 Blob under a.key for a
// brought-in sound, drafts under review, one sound in the trash and a reference file.
function v1Board() {
  const made = window.STUDIO_DATA.ASSETS.filter((a) => a.layers && a.layers.length && !a.loop && !a.music);
  if (made.length < 4) throw new Error('the sample board has too few short sounds for this fixture');
  const at = (n) => new Date(1700000000000 + n * 60000);
  const old = (d, more) => ({ ...structuredClone(d), status: 'draft', current: 0, pick: -1, chat: [], versions: [], drafts: [], hasSource: false, ...more });
  const source = Float32Array.from({ length: 2205 }, (_, i) => 0.4 * Math.sin(i / 7));
  const board = {
    v: 1, game: 'Moon Farm', brief: 'calm', platform: 'mobile', demo: false, stage: 'sample', loud: [-20, -14],
    projectRefs: [{ id: 'r1', kind: 'audio', name: 'ref.wav', key: 'ref:r1' }], agentLog: [], dynamics: [],
    assets: [
      old(made[0], { status: 'approved', current: 1, chat: [{ me: true, text: 'brighter' }], versions: [{ change: {}, note: null, at: at(1) }, { change: { shift: 1.25, stretch: 0.7, level: 1 }, note: 'brighter', at: at(2) }] }),
      old({ id: 'sfx_hit', name: 'Hit', cat: made[0].cat, layers: [], imported: true, file: 'sounds/hit.wav', license: 'CC0-1.0', holder: 'Kim' }, { status: 'approved', key: 'kimported', hasSource: true, versions: [{ change: {}, note: { key: 'importedNote' }, at: at(3) }] }),
      old({ id: 'sfx_step', name: 'Step', cat: made[0].cat, layers: [], imported: true, file: 'step.wav', license: '', holder: '' }, { status: 'approved', key: 'kstep', hasSource: true, versions: [{ change: {}, note: { key: 'importedNote' }, at: at(4) }] }),
      old(made[1], { status: 'review', pick: 1, versions: [{ change: {}, note: null, at: at(5) }], drafts: [{ change: { shift: 1.1, stretch: 0.95 }, note: { key: 'draft', text: 'softer', k: 1 }, at: at(6) }, { change: { shift: 0.98, stretch: 1.09 }, note: { key: 'draft', text: 'softer', k: 2 }, at: at(6) }] }),
      old(made[2], { status: 'pending' }),
    ],
    trash: [old(made[3], { versions: [{ change: {}, note: null, at: at(7) }] })],
  };
  const audio = { kimported: new Blob([source]), kstep: new Blob([source.slice(0, 1000)]), 'ref:r1': new Blob([new Uint8Array([1, 2, 3, 4, 5])]) };
  return { board, audio, source };
}
"""


def node(script):
    # stdin: Windows caps a command line at 32K. The timeout turns a promise that never settles into a failure.
    out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
    return json.loads(out.stdout)


def run(body):
    """The modules the way the browser loads them, then `body`, which prints one JSON value."""
    src = "globalThis.window = globalThis;\n" + "\n".join((ROOT / f).read_text(encoding="utf-8") for f in FILES) + HELPERS
    return node(src + "\n(async () => {\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });")


# ---------- a board saved before version records ----------

def test_a_v1_board_opens_with_the_same_assets_and_versions_and_its_copy_stays_as_board_v1():
    got = run(r"""
    const fx = v1Board(), fake = fakeIdb(), locks = fakeLocks();
    fake.seed({ board: fx.board }, fx.audio);
    const before = JSON.stringify(fx.board);
    const p = await open(fake, locks);
    out.result = [p.got, p.result];
    out.counts = [counts(p.assets), counts(p.trash)]; out.want = [counts(fx.board.assets), counts(fx.board.trash)];
    const all = [...p.assets, ...p.trash].flatMap((a) => [...a.versions, ...a.drafts]);
    out.total = all.length;
    out.ids = all.every((v) => typeof v.id === 'string' && v.id) && new Set(all.map((v) => v.id)).size === all.length;
    out.engines = [...new Set(all.map((v) => v.engine))];
    out.sources = p.assets.map((a) => (a.versions[0] ? a.versions[0].sources : null));
    out.draftSources = p.assets[3].drafts.map((v) => v.sources);
    out.recipes = p.assets[0].versions.map((v) => [v.change, v.note, +v.at]);
    out.state = p.assets.map((a) => [a.status, a.current, a.pick]);
    out.source = [p.assets[1].source instanceof Float32Array, p.assets[1].source.length, p.assets[1].source.every((x, i) => x === fx.source[i]), p.assets[2].source.length];
    out.ref = Array.from(p.refs.get('ref:r1'));
    out.game = p.game;
    // reading wrote nothing: the old record is still the one on disk
    out.afterRead = [fake.log.length, fake.board().v, fake.board('board.v1') === undefined];
    // legacy versions are rendered the first time they are heard, made ones and brought-in ones alike
    const a0 = p.assets[0], v0 = p.store.filled(a0, a0.versions[a0.current]);
    out.rendered = [v0.sound.rate, v0.sound.channels, v0.sound.chans[0] === v0.sound.mix, v0.sound.stems.length >= 1, v0.sound.stems.every((s) => s.chans[0] === s.data), v0.peaks.length, typeof v0.measure.loud];
    const heard = await p.store.ensureSound(p.assets[1].versions[0], p.assets[1]);
    out.importedPlays = [heard.rate, heard.mix.length > 0];
    // a change in memory before the first save does not reach the copy
    p.assets[0].chat.push({ me: true, text: 'said after opening' });
    out.saved = await p.store.save();
    out.firstWrite = fake.log[0];
    out.v = fake.board().v;
    out.copy = JSON.stringify(fake.board('board.v1')) === before;
    out.record = [fake.board().assets.map((a) => [a.id, a.versions.length, a.drafts.length]), fake.board().trash.map((a) => [a.id, a.versions.length, a.drafts.length])];
    out.recordVersion = Object.keys(fake.board().assets[0].versions[1]).sort();
    out.audio = fake.audioKeys();
    // the next save leaves the copy alone
    p.game = 'Moon Farm 2'; await p.store.save();
    out.copyKept = JSON.stringify(fake.board('board.v1')) === before;
    // the next visit reads v2 back: the same counts and ids, and the copy has done its job
    locks.release();
    const p2 = await open(fake, locks);
    out.again = [p2.got, p2.result, p2.game];
    out.counts2 = [counts(p2.assets), counts(p2.trash)];
    out.sameIds = JSON.stringify(p2.assets.map((a) => [...a.versions, ...a.drafts].map((v) => v.id))) === JSON.stringify(p.assets.map((a) => [...a.versions, ...a.drafts].map((v) => v.id)));
    out.copyGone = fake.board('board.v1') === undefined;
    out.stillPlays = (await p2.store.ensureSound(p2.assets[1].versions[0], p2.assets[1])).mix.length > 0;
    """)
    assert got["result"] == [True, "restored"]
    assert got["counts"] == got["want"] and got["total"] == 8
    assert [n for _, n, _ in got["counts"][0]] == [2, 1, 1, 1, 0] and [d for _, _, d in got["counts"][0]] == [0, 0, 0, 2, 0]
    assert got["ids"] and got["engines"] == ["legacy"]
    imported = [{"name": "sounds/hit.wav", "license": "CC0-1.0", "holder": "Kim", "use": "Imported sound"}]
    assert got["sources"] == [[SYNTH], imported, [], [SYNTH], None]  # nothing recorded for a brought-in sound is an empty list
    assert got["draftSources"] == [[SYNTH], [SYNTH]]
    assert got["recipes"] == [[{}, None, 1700000060000], [{"shift": 1.25, "stretch": 0.7, "level": 1}, "brighter", 1700000120000]]
    assert got["state"] == [["approved", 1, -1], ["approved", 0, -1], ["approved", 0, -1], ["review", 0, 1], ["pending", 0, -1]]
    assert got["source"] == [True, 2205, True, 1000] and got["ref"] == [1, 2, 3, 4, 5] and got["game"] == "Moon Farm"
    assert got["afterRead"] == [0, 1, True]
    assert got["rendered"] == [22050, 1, True, True, True, 200, "number"] and got["importedPlays"] == [22050, True]
    assert got["saved"] is True
    # one transaction on the board store alone wrote the copy and the new record together
    assert got["firstWrite"] == {"stores": ["board"], "ops": ["put board/board.v1", "put board/board"]}
    assert got["v"] == 2 and got["copy"] and got["copyKept"]
    assert got["record"] == got["want"]
    assert got["recordVersion"] == ["at", "change", "engine", "id", "note", "sources"]  # a legacy version is saved as its recipe
    assert got["audio"] == ["kimported", "kstep", "ref:r1"]
    assert got["again"] == [True, "restored", "Moon Farm 2"] and got["counts2"] == got["want"] and got["sameIds"]
    assert got["copyGone"] and got["stillPlays"]


def test_upgrade_snapshot_adds_id_engine_and_sources_and_refuses_what_it_cannot_read():
    got = run(r"""
    const fx = v1Board(), old = { ...fx.board }; delete old.v; // the first boards had no v at all
    const before = JSON.stringify(old);
    let n = 0;
    const up = S.upgradeSnapshot(old, { id: () => 'id' + (++n) });
    out.v = up.v; out.untouched = JSON.stringify(old) === before;
    out.versions = up.assets[0].versions.map((v) => [v.id, v.engine, v.sources.length, v.note]);
    out.drafts = up.assets[3].drafts.map((v) => v.id); out.trash = up.trash[0].versions.map((v) => v.engine);
    out.kept = [up.game, up.assets.length, up.assets[1].key, up.assets[1].hasSource];
    const v2 = { v: 2, assets: [], trash: [] };
    out.same = S.upgradeSnapshot(v2) === v2;
    const why = (x) => { try { S.upgradeSnapshot(x); return null; } catch (e) { return e.message; } };
    out.refused = [why(null), why('board'), why({}), why({ assets: {} }), why({ v: 3, assets: [] }), why({ v: '2', assets: [] }), why({ v: 1, assets: [null] }), why({ v: 1, assets: [{ id: 'a', versions: ['x'] }] })].map((m) => typeof m === 'string' && m.length > 0);
    out.loose = S.upgradeSnapshot({ assets: [{ id: 'a' }] }).assets[0];
    """)
    assert got["v"] == 2 and got["untouched"]
    assert got["versions"] == [["id1", "legacy", 1, None], ["id2", "legacy", 1, "brighter"]]
    assert len(got["drafts"]) == 2 and got["trash"] == ["legacy"]
    assert got["kept"] == ["Moon Farm", 5, "kimported", True]
    assert got["same"] and all(got["refused"])
    assert got["loose"] == {"id": "a", "versions": [], "drafts": []}


# ---------- restore: empty, restored, failed ----------

def test_a_board_that_cannot_be_read_is_failed_and_nothing_is_written_after_it():
    got = run(r"""
    const tryOne = async (name, prepare, extra = () => ({})) => {
      const fake = fakeIdb(), locks = fakeLocks(), timers = [];
      fake.seed({ board: { v: 2, game: 'Kept', assets: [row('a', { versions: [nkido('x')] })], trash: [] } }, { 'ver:x': new Blob(['x']) });
      prepare(fake);
      const before = fake.disk();
      const p = page(fake, locks, extra(timers));
      const read = async () => { const r = p.store.restore(); await settle(); timers.splice(0).forEach((fn) => fn()); return r; };
      await p.store.lock();
      const result = await read();
      // the page goes on with the sample board it started with, and tries to save it every way there is
      p.assets = [row('sample', { versions: [nkido('n1')] })]; p.store.hold('ver:n1', new Blob(['n']));
      const tries = [await p.store.save(), await p.store.saveBoard(), await p.store.saveBlob('ver:n1', new Blob(['n'])), await p.store.put('gameDir', { name: 'dir' }), await p.store.del('gameDir')];
      const flags = [p.store.paused, p.store.writable, p.store.restored];
      // "start again" is the user's own reset, the one way out of a record that will never open. Where the storage
      // itself cannot be reached it answers false (within the same three seconds) and the store goes on as it was.
      const firing = async (asked) => { await settle(); timers.splice(0).forEach((fn) => fn()); return asked; };
      const blocked = name === 'openError' || name === 'slowOpen' ? [await firing(p.store.clear()), fake.disk() === before] : null;
      // even a later read that works does not start the saving again on this visit
      fake.fail = {};
      const again = await read(), late = await p.store.save();
      const kept = { writes: fake.log.length, same: fake.disk() === before };
      // where the storage answers, the reset empties both stores even on this visit, and nothing is written after it
      const cleared = [name === 'slowOpen' ? null : await firing(p.store.clear()), fake.disk(), await p.store.save(), fake.disk()];
      out[name] = { result, tries, flags, applied: p.applied, again, late, ...kept, blocked, cleared, ms: timers.ms ?? null };
    };
    await tryOne('newer', (f) => f.stores.get('board').set('board', { v: 3, assets: [] }));
    await tryOne('notABoard', (f) => f.stores.get('board').set('board', { v: 2, assets: 'nope' }));
    await tryOne('brokenVersion', (f) => f.stores.get('board').set('board', { v: 1, assets: [{ id: 'a', versions: [null] }] }));
    await tryOne('readError', (f) => { f.fail.get = (store, key) => (key === 'board' ? new Error('disk') : null); });
    await tryOne('openError', (f) => { f.fail.open = () => new Error('storage is off'); });
    await tryOne('slowOpen', (f) => { f.never = true; }, (timers) => ({ setTimeout: (fn, ms) => { timers.push(fn); timers.ms = ms; return timers.length; }, clearTimeout: () => {} }));
    await tryOne('applyThrows', () => {}, () => ({ apply: () => { throw new Error('this page cannot show it'); } }));
    """)
    assert set(got) == {"newer", "notABoard", "brokenVersion", "readError", "openError", "slowOpen", "applyThrows"}
    for name, one in got.items():
        assert one["result"] == "failed", name
        assert one["tries"] == [False] * 5, name
        assert one["flags"] == [True, False, "failed"], name
        assert one["writes"] == 0 and one["same"], name  # the saved board is not written over by the sample board
        assert one["late"] is False, name
        if name == "slowOpen":  # this storage never answers: the reset gives up after the same three seconds
            assert one["blocked"] == [False, True] and one["cleared"][0] is None and one["cleared"][2] is False, name
        else:
            # the user's own "start again" empties both stores even on this visit, and nothing is written after it
            assert one["cleared"] == [True, "[[],[]]", False, "[[],[]]"], name
            assert one["blocked"] == ([False, True] if name == "openError" else None), name
    assert got["slowOpen"]["ms"] == 3000
    assert got["readError"]["again"] == "restored" and got["readError"]["applied"] == 1  # the failure went away; the visit stays unsaved
    assert got["newer"]["again"] == "failed" and got["newer"]["applied"] == 0


def test_no_saved_board_is_empty_and_the_page_saves_from_there():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    out.first = [p.got, p.result, p.applied, p.store.paused, p.store.ready, p.store.writable, p.store.readOnly];
    out.small = [await p.store.put('gameDir', { name: 'game' }), await p.store.get('gameDir'), await p.store.get('nothing') === undefined];
    p.game = 'Mine'; p.assets = [row('a')];
    out.saved = [await p.store.save(), fake.board().game, fake.board().v, fake.board('board.v1') === undefined];
    locks.release();
    const p2 = await open(fake, locks);
    out.next = [p2.result, p2.game, counts(p2.assets), p2.info.gameDir, p2.info.dropped, p2.info.refetch];
    out.del = [await p2.store.del('gameDir'), await p2.store.get('gameDir') === undefined];
    // an emptying that fails leaves the board as it was, and the tab goes on saving
    fake.fail.commit = () => new Error('disk');
    out.notCleared = [await p2.store.clear(), p2.store.writable, fake.board().game];
    fake.fail = {};
    p2.game = 'Still mine';
    out.goesOn = [await p2.store.save(), fake.board().game];
    // "start again": both stores are emptied and nothing is written after it
    p2.store.hold('ver:late', new Blob(['x'])); p2.assets.push(row('b', { versions: [nkido('late')] }));
    out.cleared = [await p2.store.clear(), fake.disk(), await p2.store.save(), await p2.store.saveBlob('ver:late', new Blob(['x'])), fake.disk()];
    // a browser without Web Locks is treated as the only tab
    const lone = await open(fakeIdb(), undefined);
    out.noLocks = [lone.got, lone.result, lone.store.writable];
    """)
    assert got["first"] == [True, "empty", 0, False, True, True, False]
    assert got["small"] == [True, {"name": "game"}, True]
    assert got["saved"] == [True, "Mine", 2, True]
    assert got["next"] == ["restored", "Mine", [["a", 0, 0]], {"name": "game"}, [], []]
    assert got["del"] == [True, True]
    assert got["notCleared"] == [False, True, "Mine"] and got["goesOn"] == [True, "Still mine"]
    assert got["cleared"] == [True, "[[],[]]", False, False, "[[],[]]"]
    assert got["noLocks"] == [True, "empty", True]


# ---------- writes ----------

def test_a_full_disk_on_one_blob_does_not_stop_the_board_record_and_sets_blob_full():
    got = run(r"""
    for (const mode of ['request', 'bare', 'commit']) {
      const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks), o = out[mode] = {};
      const a = row('sfx_a', { current: 2 });
      for (const hz of [220, 440, 880]) a.versions.push(await p.store.importVersion(wav([tone(480, hz)]), { note: { key: 'importedNote' }, sources: [] }));
      p.assets = [a];
      const keys = a.versions.map((v) => v.key), flags = () => keys.map((k) => p.store.saved.has(k));
      fake.bare = mode === 'bare';
      if (mode === 'commit') fake.fail.commit = (stores, ops) => (ops.some((x) => x.key === keys[1]) ? quota() : null);
      else fake.fail.put = (store, key) => (key === keys[1] ? quota() : null);
      o.first = [await p.store.save(), p.store.blobFull, flags(), p.notes.slice()];
      o.log = fake.log.map((t) => [t.stores.join(), t.ops.map((x) => x.replace(keys[0], 'ver:1'))]);
      o.onDisk = [fake.board().assets[0].versions.length, fake.audioKeys().length];
      // still full on the next save: the board is written again, and the toast is not repeated
      o.second = [await p.store.save(), p.store.blobFull, p.notes.slice()];
      // what is not on disk yet still plays, from memory
      o.plays = (await p.store.ensureSound(a.versions[1], a)).mix.length;
      // room again: the waiting sounds are written, one transaction each, and the flag comes down
      fake.fail = {};
      const n = fake.log.length;
      o.third = [await p.store.save(), p.store.blobFull, flags(), fake.audioKeys().length];
      o.thirdLog = fake.log.slice(n).map((t) => [t.stores.join(), t.ops.length, t.ops[0].split('/')[0]]);
      // and a later full disk is told again
      fake.fail.put = (store) => (store === 'audio' ? quota() : null);
      a.versions.push(await p.store.importVersion(wav([tone(480, 990)]), {}));
      o.later = [await p.store.save(), p.store.blobFull, p.notes.slice()];
    }
    """)
    for mode in ("request", "bare", "commit"):
        o = got[mode]
        assert o["first"] == [True, True, [True, False, False], ["saveFull"]], mode
        # the board record first, in a transaction of its own; then one sound per transaction until the one that did not fit
        assert o["log"] == [["board", ["put board/board"]], ["audio", ["put audio/ver:1"]]], mode
        assert o["onDisk"] == [3, 1], mode
        assert o["second"] == [True, True, ["saveFull"]], mode
        assert o["plays"] == 480, mode
        assert o["third"] == [True, False, [True, True, True], 3], mode
        assert o["thirdLog"] == [["board", 1, "put board"], ["audio", 1, "put audio"], ["audio", 1, "put audio"]], mode
        assert o["later"] == [True, True, ["saveFull", "saveFull"]], mode


def test_a_sound_that_does_not_fit_does_not_keep_the_others_off_the_disk():
    got = run(r"""
    const little = (store, key, value) => (store === 'audio' && value.size > 10000 ? quota() : null); // room for anything under 10 kB
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    fake.fail.put = little;
    const big = await p.store.importVersion(wav([tone(48000)]), {}), mid = await p.store.importVersion(wav([tone(480)]), {}), small = await p.store.importVersion(wav([tone(240)]), {});
    p.assets = [row('a_big', { versions: [big] }), row('a_mid', { versions: [mid] }), row('a_small', { versions: [small] })];
    p.refs.set('ref:r1', new Uint8Array([1, 2, 3]));
    const names = { [big.key]: 'big', [mid.key]: 'mid', [small.key]: 'small' }, onDisk = () => fake.audioKeys().map((k) => names[k] || k).sort();
    out.first = [await p.store.save(), p.store.blobFull, onDisk(), p.notes.slice()];
    // the next saves try the big one again, write nothing twice and do not say it again
    const n = fake.log.length;
    out.second = [await p.store.save(), await p.store.save(), p.store.blobFull, onDisk(), p.notes.slice(), fake.log.slice(n).map((t) => t.stores.join())];
    // the next visit loses the sound that never fitted, and only that one
    locks.release();
    const q = await open(fake, locks);
    out.next = [q.result, counts(q.assets), q.info.dropped.map((x) => x.asset)];

    // in one round nothing as big as a sound that did not fit is tried; the smaller ones are
    const f2 = fakeIdb(), x = await open(f2, fakeLocks()), tried = [];
    const sized = [];
    for (const [len, hz] of [[480, 440], [240, 440], [960, 440], [480, 660]]) sized.push(await x.store.importVersion(wav([tone(len, hz)]), {}));
    x.assets = sized.map((v, i) => row('s' + i, { versions: [v] }));
    f2.fail.put = (store, key, value) => { if (store !== 'audio') return null; tried.push(value.size); return quota(); };
    out.round = [await x.store.save(), tried.slice(), x.store.blobFull, x.notes.slice()];
    f2.fail = {};
    out.roundAfter = [await x.store.save(), x.store.blobFull, f2.audioKeys().length];

    // the sound that did not fit is deleted for good: nothing waits for room any more, and a later one is told again
    const f3 = fakeIdb(), r = await open(f3, fakeLocks());
    f3.fail.put = little;
    const lone = await r.store.importVersion(wav([tone(48000)]), {});
    r.assets = [row('a_big', { versions: [lone] })];
    out.stuck = [await r.store.save(), r.store.blobFull, r.notes.slice()];
    r.assets = [];
    out.removed = [await r.store.save(), r.store.blobFull, await r.store.bytes(lone.key).then(() => 'held', () => 'gone')];
    r.assets = [row('a_big2', { versions: [await r.store.importVersion(wav([tone(48000, 660)]), {})] })];
    out.again = [await r.store.save(), r.store.blobFull, r.notes.slice()];

    // a board record that did not fit, then fitted, does not use up the toast of a sound that does not fit later
    const f4 = fakeIdb(), s = await open(f4, fakeLocks());
    s.assets = [row('a')];
    f4.fail.put = (store, key) => (key === 'board' ? quota() : null);
    out.boardFull = [await s.store.save(), s.store.blobFull, s.notes.slice()];
    f4.fail = {};
    out.boardBack = [await s.store.save(), s.notes.slice()];
    f4.fail.put = (store) => (store === 'audio' ? quota() : null);
    s.assets[0].versions.push(await s.store.importVersion(wav([tone(480)]), {}));
    out.thenBlob = [await s.store.save(), s.store.blobFull, s.notes.slice()];
    // the board record and a sound not fitting in the same save is one full disk, said once
    const f5 = fakeIdb(), u = await open(f5, fakeLocks());
    f5.fail.put = () => quota();
    u.assets = [row('a', { versions: [await u.store.importVersion(wav([tone(480)]), {})] })];
    out.both = [await u.store.save(), u.store.blobFull, u.notes.slice(), await u.store.save(), u.notes.slice()];

    // saveBlob on its own (a fetched result): no room sets blobFull and keeps the sound in memory, where it plays from
    const f6 = fakeIdb(), w = await open(f6, fakeLocks());
    f6.fail.put = (store) => (store === 'audio' ? quota() : null);
    out.direct = [await w.store.saveBlob('ver:j1', new Blob([wav([tone(480)])])), w.store.blobFull, w.store.saved.has('ver:j1'), w.notes.slice(), (await w.store.bytes('ver:j1')).length];
    // the board names it as a draft: every save tries it again, and with room it is written and the flag comes down
    w.assets = [row('a', { status: 'working', drafts: [nkido('j1')] })];
    out.directStill = [await w.store.save(), w.store.blobFull];
    f6.fail = {};
    out.directLater = [await w.store.save(), w.store.blobFull, w.store.saved.has('ver:j1'), f6.audioKeys()];
    """)
    assert got["first"] == [True, True, ["mid", "ref:r1", "small"], ["saveFull"]]
    assert got["second"] == [True, True, True, ["mid", "ref:r1", "small"], ["saveFull"], ["board", "board"]]
    assert got["next"] == ["restored", [["a_big", 0, 0], ["a_mid", 1, 0], ["a_small", 1, 0]], ["a_big"]]
    assert got["round"] == [True, [1004, 524], True, ["saveFull"]]  # 1004 did not fit, 524 was still tried, 1964 and the other 1004 were not
    assert got["roundAfter"] == [True, False, 4]
    assert got["stuck"] == [True, True, ["saveFull"]]
    assert got["removed"] == [True, False, "gone"]
    assert got["again"] == [True, True, ["saveFull", "saveFull"]]
    assert got["boardFull"] == [False, False, ["saveFull"]] and got["boardBack"] == [True, ["saveFull"]]
    assert got["thenBlob"] == [True, True, ["saveFull", "saveFull"]]
    assert got["both"] == [False, True, ["saveFull"], False, ["saveFull"]]
    assert got["direct"] == [False, True, False, ["saveFull"], 1004]
    assert got["directStill"] == [True, True]
    assert got["directLater"] == [True, False, True, ["ver:j1"]]


def test_a_board_only_write_is_followed_by_the_sounds_still_owed_their_write():
    # A request about to be sent writes the board record alone. A sound brought in a moment before has no bytes on
    # disk yet, and a reload then would bring its tile back empty: the whole save follows without the page asking.
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    p.assets = [row('a', { versions: [nkido('n1')] })]; p.store.hold('ver:n1', new Blob(['n']));
    const n = fake.log.length;
    out.board = await p.store.saveBoard();
    out.first = fake.log[n];
    await p.store.put('wait', 1); // behind the save that is already on its way; this asks for none itself
    out.audio = fake.audioKeys();
    out.saved = p.store.saved.has('ver:n1');
    // nothing is owed any more: a board-only write is one write again
    const m = fake.log.length;
    await p.store.saveBoard(); await p.store.put('x', 1);
    out.after = fake.log.slice(m).map((t) => t.ops.join());
    // a sound that did not fit is not chased by every board write
    const q = fakeIdb(), p2 = await open(q, fakeLocks());
    q.fail.put = (store, key) => (key === 'ver:n2' ? quota() : null);
    p2.assets = [row('b', { versions: [nkido('n2')] })]; p2.store.hold('ver:n2', new Blob(['n']));
    await p2.store.save();
    const k = q.log.length;
    await p2.store.saveBoard(); await p2.store.put('x', 1);
    out.stuck = [p2.store.blobFull, q.log.slice(k).map((t) => t.ops.join())];
    """)
    assert got["board"] is True and got["first"] == {"stores": ["board"], "ops": ["put board/board"]}
    assert got["audio"] == ["ver:n1"] and got["saved"] is True
    assert got["after"] == ["put board/board", "put board/x"]
    assert got["stuck"] == [True, ["put board/board", "put board/x"]]


def test_save_board_and_save_blob_answer_true_or_false_and_only_finished_keys_count_as_saved():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    p.assets = [row('a')];
    out.board = [await p.store.saveBoard(), fake.log.at(-1)];
    out.blob = [await p.store.saveBlob('ver:j1', new Blob(['abc'])), fake.log.at(-1), p.store.saved.has('ver:j1')];
    fake.fail.put = () => new Error('disk');
    out.fails = [await p.store.saveBoard(), await p.store.saveBlob('ver:j2', new Blob(['x'])), p.store.saved.has('ver:j2'), p.store.blobFull, p.notes.length, fake.log.length];
    fake.fail.put = (store, key) => (key === 'board' ? quota() : null);
    out.fullBoard = [await p.store.saveBoard(), p.notes.length]; // the caller decides what to say
    // a snapshot that cannot be made is a save that did not happen, not a crash
    fake.fail = {};
    const broken = page(fake, undefined, { snapshot: () => { throw new Error('bad state'); } }); await broken.store.lock(); await broken.store.restore();
    out.throws = await broken.store.saveBoard();
    // asked for many times in a row, a save runs once more with the newest state
    const n = fake.log.length;
    p.game = 'one'; const s1 = p.store.save(); p.game = 'two'; const s2 = p.store.save(); p.game = 'three'; const s3 = p.store.save();
    out.coalesced = [s1 === s2 && s2 === s3, await s3, fake.board().game, fake.log.length - n];
    """)
    assert got["board"] == [True, {"stores": ["board"], "ops": ["put board/board"]}]
    assert got["blob"] == [True, {"stores": ["audio"], "ops": ["put audio/ver:j1"]}, True]
    assert got["fails"] == [False, False, False, False, 0, 2]
    assert got["fullBoard"] == [False, 0]
    assert got["throws"] is False
    assert got["coalesced"] == [True, True, "three", 1]


def test_unused_sounds_are_deleted_in_their_own_transaction_and_only_after_the_board_was_saved():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    const a = row('a'), old = row('old', { key: 'kold', source: Float32Array.from([0.1, 0.2, 0.3]), versions: [legacy('l1', 1)] });
    for (const hz of [220, 440]) a.versions.push(await p.store.importVersion(wav([tone(240, hz)]), {}));
    const [k1, k2] = a.versions.map((v) => v.key);
    p.assets = [a, old]; p.refs.set('ref:r1', new Uint8Array([9, 8, 7]));
    out.first = [await p.store.save(), fake.audioKeys().length, fake.log.map((t) => t.stores.join() + ':' + t.ops.length)];
    out.kept = [new Float32Array(await fake.stores.get('audio').get('kold').arrayBuffer()).length, Array.from(new Uint8Array(await fake.stores.get('audio').get('ref:r1').arrayBuffer()))];
    // one version, the old sound and the reference are taken out, but the board cannot be written: nothing is deleted
    a.versions.shift(); p.assets = [a]; p.refs.clear();
    fake.fail.put = (store, key) => (key === 'board' ? new Error('disk') : null);
    out.notYet = [await p.store.save(), fake.audioKeys().length];
    fake.fail = {};
    const n = fake.log.length;
    out.then = [await p.store.save(), fake.audioKeys().map((k) => (k === k2 ? 'second' : k))];
    out.thenLog = fake.log.slice(n).map((t) => [t.stores.join(), t.ops.map((x) => x.split(' ')[0]).join()]);
    out.forgotten = [p.store.saved.has(k1), p.store.saved.has(k2)];
    // a sound saved ahead of the board that names it (a result still being fetched) is not swept away
    out.ahead = [await p.store.saveBlob('ver:early', new Blob(['e'])), await p.store.save(), fake.audioKeys().includes('ver:early')];
    // if no board ever names it, the first save of the next visit clears it
    locks.release();
    const p2 = await open(fake, locks);
    out.next = [await p2.store.save(), fake.audioKeys().includes('ver:early'), fake.audioKeys().length];
    """)
    assert got["first"] == [True, 4, ["board:1", "audio:1", "audio:1", "audio:1", "audio:1"]]
    assert got["kept"] == [3, [9, 8, 7]]
    assert got["notYet"] == [False, 4]
    assert got["then"] == [True, ["second"]]
    assert got["thenLog"] == [["board", "put"], ["audio", "delete,delete,delete"]]
    assert got["forgotten"] == [False, True]
    assert got["ahead"] == [True, True, True]
    assert got["next"] == [True, False, 1]


# ---------- versions whose sound is gone ----------

def test_a_version_whose_blob_is_missing_is_dropped_alone():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks();
    const three = (id, more) => row(id, { status: 'approved', current: 1, versions: [nkido(id + '1', { at: 1000 }), nkido(id + '2', { at: 3000, stems: [{ label: 'lead', key: 'ver:' + id + '2:s1', bytes: 1, sha256: null }] }), nkido(id + '3', { at: 2000 })], ...more });
    const making = (id) => ({ status: 'working', work: { request: 'r-' + id, kind: 'acct', who: 'w', mode: 'revise', text: 'softer', n: 1, at: 1, before: 'approved', jobs: [{ id: id + '9', k: 1, got: false }] } });
    const board = { v: 2, game: 'G', trash: [three('t'), three('u')], assets: [
      three('a'), three('b'), three('h', making('h')), row('i', { versions: [nkido('i1')], ...making('i') }), three('k', { status: 'draft' }),
      three('c', { status: 'working', drafts: [nkido('c9')], work: { request: 'r1', kind: 'acct', who: 'w', mode: 'revise', text: 'softer', n: 2, at: 1, before: 'approved', jobs: [{ id: 'c9', k: 1, got: true }, { id: 'c10', k: 2, got: false }] } }),
      row('d', { status: 'approved', versions: [nkido('d1')] }),
      row('e', { status: 'review', pick: 1, versions: [nkido('e0')], drafts: [nkido('e1'), nkido('e2')] }),
      three('f'),
      row('g', { status: 'review', pick: 0, versions: [nkido('g0')], drafts: [nkido('g1')] }),
    ] };
    const audio = {};
    for (const a of [...board.assets, ...board.trash]) for (const v of [...a.versions, ...a.drafts]) for (const k of S.versionKeys(v)) audio[k] = new Blob([k]);
    const lost = ['ver:a2', 'ver:b2:s1', 'ver:c9', 'ver:d1', 'ver:e2', 'ver:g1', 'ver:h2', 'ver:i1', 'ver:k2', 'ver:t3', 'ver:u2'];
    for (const k of lost) delete audio[k];
    const had = Object.keys(audio).sort();
    fake.seed({ board }, audio);
    const p = await open(fake, locks);
    out.result = p.result;
    const by = Object.fromEntries([...p.assets, ...p.trash].map((a) => [a.id, a])), ids = (list) => list.map((v) => v.id);
    out.a = [ids(by.a.versions), by.a.current, by.a.status];
    out.b = [ids(by.b.versions), by.b.current, by.b.status];
    out.c = [ids(by.c.versions), ids(by.c.drafts), by.c.current, by.c.status, by.c.pick, by.c.work.jobs];
    out.d = [ids(by.d.versions), by.d.current, by.d.status];
    out.e = [ids(by.e.versions), ids(by.e.drafts), by.e.pick, by.e.status];
    out.f = [ids(by.f.versions), by.f.current, by.f.status];
    out.g = [ids(by.g.versions), ids(by.g.drafts), by.g.pick, by.g.status];
    out.t = [ids(by.t.versions), by.t.current, by.t.status];
    out.h = [ids(by.h.versions), by.h.current, by.h.status, by.h.work.before];
    out.i = [ids(by.i.versions), by.i.status, by.i.work.before];
    out.k = [ids(by.k.versions), by.k.current, by.k.status];
    out.u = [ids(by.u.versions), by.u.current, by.u.status];
    out.info = [p.info.dropped, p.info.refetch];
    out.untouched = [fake.log.length, JSON.stringify(fake.audioKeys()) === JSON.stringify(had)];
    // the sounds of the other versions stay; what the dropped versions left behind goes with the next save
    out.saved = await p.store.save();
    out.gone = had.filter((k) => !fake.audioKeys().includes(k));
    out.last = fake.log.at(-1).stores;
    """)
    assert got["result"] == "restored"
    # the version in use went: the newest one left takes over. It was never approved (the approval was the lost
    # version's), so the sound is a draft again
    assert got["a"] == [["a1", "a3"], 1, "draft"]
    assert got["b"] == [["b1", "b3"], 1, "draft"]  # one missing stem makes the version not whole
    # a job record still names c9: it is fetched again, and the work goes on
    assert got["c"] == [["c1", "c2", "c3"], [], 1, "working", -1, [{"id": "c9", "k": 1, "got": False}, {"id": "c10", "k": 2, "got": False}]]
    assert got["d"] == [[], 0, "pending"]
    assert got["e"] == [["e0"], ["e1"], 0, "review"]
    assert got["f"] == [["f1", "f2", "f3"], 1, "approved"]
    assert got["g"] == [["g0"], [], -1, "draft"]
    assert got["t"] == [["t1", "t2"], 1, "approved"]  # not the version in use: nothing else moves (the trash is mended too)
    # a sound being remade stays working; what it goes back to if nothing comes of it loses the approval the same way,
    # and is an empty slot when no version is left
    assert got["h"] == [["h1", "h3"], 1, "working", "draft"] and got["i"] == [[], "working", "pending"]
    assert got["k"] == [["k1", "k3"], 1, "draft"]     # a draft stays a draft
    assert got["u"] == [["u1", "u3"], 1, "draft"]     # in the trash too
    dropped = [{"asset": x, "id": y} for x, y in (("a", "a2"), ("b", "b2"), ("h", "h2"), ("i", "i1"), ("k", "k2"), ("d", "d1"), ("e", "e2"), ("g", "g1"), ("t", "t3"), ("u", "u2"))]
    assert got["info"] == [dropped, [{"asset": "c", "id": "c9"}]]
    assert got["untouched"] == [0, True]
    assert got["saved"] is True and got["gone"] == ["ver:a2:s1", "ver:b2", "ver:h2:s1", "ver:k2:s1", "ver:u2:s1"] and got["last"] == ["audio"]


def test_an_old_brought_in_sound_without_its_blob_comes_back_empty_and_the_rest_stays():
    got = run(r"""
    const fx = v1Board(), fake = fakeIdb(), locks = fakeLocks();
    delete fx.audio.kimported;
    fx.audio.kstep = new Blob([new Uint8Array(7)]); // not Float32 data: as good as gone
    fake.seed({ board: fx.board }, fx.audio);
    const p = await open(fake, locks);
    out.result = p.result;
    out.counts = counts(p.assets);
    out.lost = [p.assets[1], p.assets[2]].map((a) => [a.status, a.current, a.source === undefined]);
    out.dropped = p.info.dropped.map((x) => x.asset);
    """)
    assert got["result"] == "restored"
    assert [n for _, n, _ in got["counts"]] == [2, 0, 0, 1, 0]
    assert got["lost"] == [["pending", 0, True], ["pending", 0, True]]
    assert got["dropped"] == ["sfx_hit", "sfx_step"]


def test_prune_only_removes_legacy_versions():
    got = run(r"""
    const make = () => [
      row('a', { current: 4, versions: [legacy('l1', 1), nkido('n1', { at: 2 }), legacy('l2', 3), { ...nkido('i1', { at: 0 }), engine: 'import' }, legacy('l3', 5), legacy('l4', 4)] }),
      row('b', { current: 0, versions: [nkido('n2', { at: 1 }), nkido('n3', { at: 2 })] }),
    ];
    const ids = (list) => list.map((a) => a.versions.map((v) => v.id));
    const pure = make(), cut = [];
    for (let n = S.prune(pure); n; n = S.prune(pure)) cut.push(n);
    out.pure = [cut, ids(pure), pure[0].versions[pure[0].current].id];
    // the board record does not fit until two old legacy versions are gone
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    p.assets = make();
    const count = (value) => value.assets.flatMap((x) => x.versions).filter((v) => v.engine === 'legacy').length;
    fake.fail.put = (store, key, value) => (key === 'board' && count(value) > 2 ? quota() : null);
    out.fits = [await p.store.save(), p.notes.slice(), ids(p.assets), p.assets[0].versions[p.assets[0].current].id, fake.board().assets.map((a) => a.versions.length)];
    // it never fits: the legacy versions that may go are gone, the nkido and import ones are all still there
    const never = fakeIdb(), r = await open(never, fakeLocks());
    r.assets = make();
    never.fail.put = (store, key) => (key === 'board' ? quota() : null);
    out.never = [await r.store.save(), r.notes.slice(), ids(r.assets), r.assets[0].versions[r.assets[0].current].id, never.log.length];
    """)
    assert got["pure"] == [[2, 1], [["n1", "i1", "l3"], ["n2", "n3"]], "l3"]
    assert got["fits"] == [True, ["pruned 2"], [["n1", "i1", "l3", "l4"], ["n2", "n3"]], "l3", [4, 2]]
    assert got["never"] == [False, ["saveFull"], [["n1", "i1", "l3"], ["n2", "n3"]], "l3", 0]


# ---------- one tab at a time ----------

def guard_allow():
    """The selector app.js hands the guard: what a view-only tab may still use."""
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    return re.search(r"store\.guard\(window, \{ allow: '([^']+)'", app).group(1)


def test_a_tab_without_the_lock_changes_nothing_and_reads_the_board_again_when_it_gets_the_lock():
    allow = guard_allow()
    # the spec's list, and the download link of the export: "exporting still works here" has to be true
    assert allow.split(", ") == ["#playAll", "#exportBtn", "#backBtn", "#menuBtn", "#dialog.free", "a[download]"]
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks();
    const A = await open(fake, locks);
    const a = row('sfx_a', { name: 'First', status: 'approved', versions: [await A.store.importVersion(wav([tone(480), tone(480, 660)]), { note: null, sources: [] })] });
    A.assets = [a]; A.game = 'From A';
    out.A = [A.got, A.result, await A.store.save()];
    // the same board in a second tab
    const B = await open(fake, locks);
    out.B = [B.got, B.result, B.store.locked, B.store.ready, B.store.readOnly, B.store.writable, B.store.paused];
    out.shows = [B.game, counts(B.assets)];
    // the guard: clicks, keys, drops and submits stop in the capture phase, but for what stays usable
    // The selector for what stays usable is the one app.js hands the guard. 'stopped': cancelled and kept from every
    // handler of the page. 'hushed': left to the browser, but no handler of the page hears it. 'passed': untouched.
    const heard = {}, stopped = [];
    B.store.guard({ addEventListener: (type, fn, capture) => { heard[type] = [fn, capture]; } }, { allow: ALLOW, blocked: (e) => stopped.push(e.type) });
    const send = (type, on, more = {}) => {
      const e = { type, target: { closest: (q) => (q.split(',').map((s) => s.trim()).includes(on) ? {} : null) }, prevented: false, halted: false, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.halted = true; }, ...more };
      heard[type][0](e);
      return e.prevented && e.halted ? 'stopped' : e.halted ? 'hushed' : e.prevented ? 'cancelled only' : 'passed';
    };
    const press = () => [send('click', '.tile'), send('click', '#playAll'), send('click', '#exportBtn'), send('click', '#dialog.free'), send('click', '#backBtn'), send('click', '#menuBtn'),
      send('click', 'a[download]'), send('click', 'a'), send('keydown', 'body', { key: 'a' }), send('keydown', 'body', { key: 'Delete' }),
      send('keydown', 'body', { key: 'Tab' }), send('keydown', 'body', { key: 'Escape' }), send('keydown', 'body', { key: 'r', ctrlKey: true }),
      send('keydown', 'body', { key: 'a', altKey: true }), send('keydown', 'body', { key: 'Delete', ctrlKey: true }), send('keydown', 'body', { key: 'x', metaKey: true }),
      send('keydown', 'body', { key: 'Tab', ctrlKey: true }), send('keydown', '#dialog.free', { key: 'a', ctrlKey: true }), send('drop', '#board'), send('submit', 'form')];
    out.guard = [Object.keys(heard).sort(), Object.values(heard).every(([, capture]) => capture === true), press(), stopped.slice()];
    // whatever it tries, the saved board stays as the first tab left it
    const before = fake.disk(), writes = fake.log.length;
    B.game = 'From B'; B.assets.push(row('sfx_b', { versions: [await B.store.importVersion(wav([tone(240)]), {})] }));
    out.tries = [await B.store.save(), await B.store.saveBoard(), await B.store.saveBlob('ver:zz', new Blob(['z'])), await B.store.put('gameDir', { name: 'x' }), await B.store.del('gameDir'), await B.store.clear()];
    out.unchanged = [fake.disk() === before, fake.log.length === writes];
    // listening needs no lock
    out.listens = (await B.store.ensureSound(B.assets[0].versions[0], B.assets[0])).channels;
    // the first tab goes on working, then closes
    A.game = 'Later in A'; a.name = 'Renamed'; a.versions.push(await A.store.importVersion(wav([tone(100)]), {})); a.current = 1;
    await A.store.save();
    const final = JSON.stringify(fake.board());
    out.waiting = locks.waiting;
    locks.release();
    for (let i = 0; i < 100 && !B.took.length; i++) await settle();
    out.took = B.took.slice();
    out.after = [B.store.locked, B.store.ready, B.store.readOnly, B.store.writable];
    out.equal = JSON.stringify(B.snapshot()) === final;
    out.showsNow = [B.game, B.assets[0].name, counts(B.assets)];
    out.guardNow = press().every((x) => x === 'passed');
    B.game = 'B writes now';
    out.saves = [await B.store.save(), fake.board().game];
    // the guard on its own: closed until its open() says otherwise
    let opened = false;
    const lone = {};
    S.guard({ addEventListener: (type, fn) => { lone[type] = fn; } }, { open: () => opened });
    const hit = () => { const e = { type: 'click', target: {}, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.halted = true; } }; lone.click(e); return !!(e.prevented && e.halted); };
    out.plainGuard = [hit(), (opened = true, hit())];
    """.replace("ALLOW", json.dumps(allow)))
    assert got["A"] == [True, "empty", True]
    assert got["B"] == [False, "restored", False, False, True, False, False]
    assert got["shows"] == ["From A", [["sfx_a", 1, 0]]]
    types, capture, pressed, stopped = got["guard"]
    assert types == ["click", "drop", "keydown", "submit"] and capture
    assert pressed == [
        "stopped",  # a tile
        "passed", "passed", "passed", "passed", "passed",  # play all, export, the export dialog, back, the menu button
        "passed",   # the link exportBundle() presses to hand over the zip
        "stopped",  # any other link
        "stopped", "stopped",  # a, Delete
        "passed", "passed",    # Tab, Escape
        # Ctrl+R, Alt+A, Ctrl+Delete, Meta+X: the browser may act on them, the page's own key handlers never hear them
        "hushed", "hushed", "hushed", "hushed",
        "passed",   # Ctrl+Tab
        "passed",   # Ctrl+A inside the export dialog
        "stopped", "stopped",  # drop, submit
    ]
    assert stopped == ["click", "click", "keydown", "keydown", "drop", "submit"]  # the toast is for what was cancelled
    assert got["tries"] == [False] * 6 and got["unchanged"] == [True, True]
    assert got["listens"] == 2
    assert got["waiting"] == 1 and got["took"] == ["restored"]
    assert got["after"] == [True, True, False, True]
    assert got["equal"] and got["showsNow"] == ["Later in A", "Renamed", [["sfx_a", 2, 0]]]
    assert got["guardNow"] is True
    assert got["saves"] == [True, "B writes now"]
    assert got["plainGuard"] == [True, False]


def test_a_view_only_tab_whose_first_read_failed_stays_unsaved_after_taking_over_so_the_page_starts_over():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks();
    const A = await open(fake, locks);
    A.assets = [row('a', { status: 'approved' })]; A.game = 'From A';
    await A.store.save();
    // the second tab's first read fails once
    let fails = 1;
    fake.fail.get = (store, key) => (key === 'board' && fails-- > 0 ? new Error('disk') : null);
    const B = await open(fake, locks);
    out.first = [B.got, B.result, B.store.paused, B.store.readOnly, B.applied];
    locks.release(); // the first tab is closed
    for (let i = 0; i < 100 && !B.took.length; i++) await settle();
    // the take-over read works and the real board is applied, but a visit that failed once never saves
    out.took = [B.took.slice(), B.game, B.store.locked, B.store.ready, B.store.paused, B.store.writable];
    B.game = 'Edited in B';
    out.unsaved = [await B.store.save(), fake.board().game];
    """)
    assert got["first"] == [False, "failed", True, True, 0]
    assert got["took"] == [["restored"], "From A", True, True, True, False]
    assert got["unsaved"] == [False, "From A"]
    # so the page must not show that board as one that can be worked on: it starts over as a new visit that has the board
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    took = app[app.index("function tookOver(result) {"):app.index("async function forget()")]
    assert "if (acct || store.paused || (result === 'empty' && shown !== 'empty')) { location.reload(); return; }" in took
    assert took.index("store.paused") < took.index("renderBoard()") and took.index("store.paused") < took.index("$('toast').hidden")


# ---------- sound ----------

def test_filled_renders_legacy_versions_and_leaves_nkido_and_import_versions_as_stored():
    got = run(r"""
    const demo = window.STUDIO_DATA.ASSETS.find((a) => a.layers && a.layers.length && !a.loop && !a.music);
    let renders = 0;
    const spy = { render: (...x) => { renders++; return window.synth.render(...x); }, peaks: window.synth.peaks, measure: window.synth.measure };
    const facts = { peaks: Array.from({ length: 200 }, (_, i) => i / 200), measure: { peak: -3.2, loud: -18.4, seconds: 1.5, rate: 48000, channels: 2, bits: 16 } };
    for (const engine of ['nkido', 'import']) {
      const v = { ...nkido('n1', facts), engine }, a = { ...structuredClone(demo), versions: [v], current: 0 }, before = JSON.stringify(v);
      const back = S.filled(a, v, spy), again = S.create({ synth: spy }).filled(a, v);
      out[engine] = [back === v, again === v, 'sound' in v, JSON.stringify(v) === before, v.peaks === facts.peaks, v.measure === facts.measure, renders];
    }
    const old = { id: 'l1', at: 1, note: null, change: {}, engine: 'legacy', sources: [] }, bare = { change: { shift: 1.2 }, note: null, at: 2 }; // one from before engines had names
    const a = { ...structuredClone(demo), versions: [old, bare], current: 0 };
    S.filled(a, old, spy); S.filled(a, old, spy); S.filled(a, bare, spy);
    out.legacy = [renders, old.sound.rate, old.sound.chans.length, old.sound.chans[0] === old.sound.mix, old.peaks.length, typeof old.measure.peak, !!bare.sound];
    out.kinds = [S.isLegacy(old), S.isLegacy(bare), S.isLegacy({ engine: 'nkido' }), S.isLegacy({ engine: 'import' })];
    """)
    assert got["nkido"] == [True, True, False, True, True, True, 0]
    assert got["import"] == [True, True, False, True, True, True, 0]
    assert got["legacy"] == [2, 22050, 1, True, 200, "number", True]  # rendered once each, then kept
    assert got["kinds"] == [True, True, False, False]


def test_ensure_sound_decodes_once_into_channels_a_mix_and_stems():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    const left = tone(960, 440), right = tone(960, 660, 48000, 0.25), lead = tone(960, 880, 48000, 0.2);
    const v = nkido('job1', { stems: [{ label: 'lead', key: 'ver:job1:s1', bytes: 0, sha256: null }, { label: 'lead', key: 'ver:job1:s2', bytes: 0, sha256: null }, { label: '', key: 'ver:job1:s3', bytes: 0, sha256: null }] });
    const plain = nkido('job2'), ogg = { ...nkido('file1'), engine: 'import' }, a = row('bgm', { versions: [v, plain, ogg] });
    p.assets = [a];
    // the way a fetched result is kept: every Blob first, each in its own transaction, then the board that names them
    out.blobs = [await p.store.saveBlob('ver:job1', new Blob([wav([left, right])])), await p.store.saveBlob('ver:job1:s1', new Blob([wav([lead])])), await p.store.saveBlob('ver:job1:s2', new Blob([wav([lead, lead])])), await p.store.saveBlob('ver:job1:s3', new Blob([wav([lead])])),
      await p.store.saveBlob('ver:job2', new Blob([wav([left], 44100, 24)])), await p.store.saveBlob('ver:file1', new Blob([Uint8Array.from([79, 103, 103, 83, 64, 128, 0, 0, 1, 2])]))];
    out.board = await p.store.saveBoard();
    out.order = fake.log.map((t) => t.stores.join() + ':' + t.ops.length);
    const reads = fake.reads.length;
    const [one, two] = await Promise.all([p.store.ensureSound(v, a), p.store.ensureSound(v, a)]), three = await p.store.ensureSound(v, a);
    out.once = [one === two, two === three, v.sound === one, fake.reads.slice(reads)];
    out.shape = [one.rate, one.channels, one.seconds, one.chans.length, one.chans[0].length, one.mix.length, one.stems.map((s) => [s.name, s.chans.length, s.data.length])];
    out.exact = [Math.abs(one.chans[0][100] - left[100]) < 1e-4, Math.abs(one.chans[1][100] - right[100]) < 1e-4, Math.abs(one.mix[100] - (one.chans[0][100] + one.chans[1][100]) / 2) < 1e-7, one.stems[1].data !== one.stems[1].chans[0], one.stems[0].data === one.stems[0].chans[0]];
    // a result without stems shows its master as the one stem
    const solo = await p.store.ensureSound(plain, a);
    out.noStems = [solo.rate, solo.channels, solo.stems.map((s) => s.name), solo.stems[0].chans === solo.chans, solo.chans[0] === solo.mix];
    // what is not a WAV goes to the browser's decoder (handed in here)
    const other = await p.store.ensureSound(ogg, a);
    out.other = [p.decoded, other.rate, Array.from(other.chans[0]).slice(4, 6)];
    // the decoded sound never reaches the board record
    out.record = ['sound' in S.record(v), await p.store.saveBoard(), fake.board().assets[0].versions.some((x) => 'sound' in x)];
    // a sound that is not stored is an error the caller hears, and asking again tries again
    const none = nkido('nope');
    out.missing = [await p.store.ensureSound(none, a).then(() => 'ok', () => 'no'), await p.store.ensureSound(none, a).then(() => 'ok', () => 'no'), 'sound' in none, await p.store.ensureSound(null, a).then(() => 'ok', () => 'no')];
    // the version alone is enough for stored sound; a legacy version is rendered from its asset, and says so without it
    const fresh = nkido('job1');
    out.alone = [(await p.store.ensureSound(fresh)).chans.length, await p.store.ensureSound(legacy('l1', 1)).then(() => 'ok', (e) => e.message)];
    out.bytes = [(await p.store.bytes('ver:file1')).length, await p.store.bytes('ver:zz').then(() => 'ok', () => 'no')];
    """)
    assert got["blobs"] == [True] * 6 and got["board"] is True
    assert got["order"] == ["audio:1"] * 6 + ["board:1"]
    assert got["once"] == [True, True, True, ["audio/ver:job1", "audio/ver:job1:s1", "audio/ver:job1:s2", "audio/ver:job1:s3"]]
    assert got["shape"] == [48000, 2, 0.02, 2, 960, 960, [["lead", 1, 960], ["lead 2", 2, 960], ["stem 3", 1, 960]]]
    assert all(got["exact"])
    assert got["noStems"] == [44100, 1, ["main"], True, True]
    assert got["other"] == [1, 48000, [0.25, 0.5]]
    assert got["record"] == [False, True, False]
    assert got["missing"] == ["no", "no", False, "no"]
    assert got["alone"][0] == 2 and "ensureSound(version, asset)" in got["alone"][1]
    assert got["bytes"] == [10, "no"]


def test_a_brought_in_file_becomes_an_import_version_that_keeps_its_own_bytes():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks(), p = await open(fake, locks);
    const left = tone(4410, 440, 44100), right = tone(4410, 550, 44100, 0.25), bytes = wav([left, right], 44100, 24);
    const sources = [{ name: 'hit.wav', license: 'CC0-1.0', holder: 'Kim', use: 'Imported sound' }];
    const v = await p.store.importVersion(bytes, { note: { key: 'importedNote' }, sources });
    out.fields = Object.keys(v).sort();
    out.facts = [v.engine, v.key === 'ver:' + v.id, v.rate, v.channels, v.bits, v.bytes === bytes.length, v.peaks.length, v.stems, v.issues, v.note, v.sources, typeof v.at, v.job, v.parent, v.draft, v.source];
    out.sha = [v.sha256, require('crypto').createHash('sha256').update(bytes).digest('hex')];
    out.measured = [Math.abs(v.seconds - 0.1) < 1e-9, v.measure.seconds === v.seconds, v.measure.rate, v.measure.channels, v.measure.bits, Math.abs(v.measure.sample_peak - 20 * Math.log10(0.5)) < 0.01, Math.max(...v.peaks) > 0.49 && Math.max(...v.peaks) <= 0.5];
    const second = await p.store.importVersion(wav([tone(100)]), {});
    out.ids = [v.id !== second.id, /^v[0-9a-z]+$/.test(v.id), p.store.newId() !== p.store.newId()];
    const a = row('sfx_hit', { imported: true, status: 'approved', versions: [v] });
    p.assets = [a];
    // heard before it is saved, from the bytes still in memory
    out.early = (await p.store.ensureSound(v, a)).chans.length;
    out.saved = [await p.store.save(), p.store.saved.has(v.key)];
    const kept = new Uint8Array(await fake.stores.get('audio').get(v.key).arrayBuffer());
    out.sameBytes = kept.length === bytes.length && kept.every((b, i) => b === bytes[i]);
    out.record = Object.keys(fake.board().assets[0].versions[0]).sort();
    locks.release();
    const p2 = await open(fake, locks), v2 = p2.assets[0].versions[0];
    out.next = [p2.result, v2.engine, 'sound' in v2, v2.peaks.length, v2.measure.channels, fake.reads.filter((r) => r.startsWith('audio/')).length];
    const s = await p2.store.ensureSound(v2, p2.assets[0]);
    out.heard = [s.rate, s.channels, s.chans[0].length, Math.abs(s.chans[1][1000] - right[1000]) < 1e-6, s.stems.map((x) => x.name)];
    // what cannot be heard is not taken in
    out.bad = [await p.store.importVersion(wav([new Float32Array(0)]), {}).then(() => 'ok', () => 'no'), await p.store.importVersion(Uint8Array.from([1, 2, 3]), {}).then(() => 'ok', () => 'no')];
    out.helpers = [S.importSources({ file: 'a.wav', license: 'CC-BY-4.0', holder: 'Lee' }), S.importSources({ file: 'a.wav', license: '' }), S.sourcesFor({ imported: true, id: 'x', license: 'CC0-1.0' }), S.sourcesFor({ id: 'made' })];
    out.keys = [S.versionKeys(nkido('j', { stems: [{ label: 'a', key: 'ver:j:s1' }, { label: 'b', key: 'ver:j:s2' }] })), S.versionKeys({ id: 'l', engine: 'legacy' }), S.versionKeys(v)[0] === v.key];
    """)
    assert got["fields"] == RECORD
    assert got["facts"] == ["import", True, 44100, 2, 24, True, 200, [], [], {"key": "importedNote"}, [{"name": "hit.wav", "license": "CC0-1.0", "holder": "Kim", "use": "Imported sound"}], "number", None, None, None, None]
    assert got["sha"][0] == got["sha"][1] and len(got["sha"][0]) == 64
    assert all(got["measured"]) and all(got["ids"])
    assert got["early"] == 2 and got["saved"] == [True, True] and got["sameBytes"]
    assert got["record"] == RECORD  # everything but the decoded sound
    assert got["next"] == ["restored", "import", False, 200, 2, 0]  # a version's sound is not read until it is heard
    assert got["heard"] == [44100, 2, 4410, True, ["main"]]
    assert got["bad"] == ["no", "no"]
    assert got["helpers"] == [
        [{"name": "a.wav", "license": "CC-BY-4.0", "holder": "Lee", "use": "Imported sound"}], [],
        [{"name": "x", "license": "CC0-1.0", "holder": "", "use": "Imported sound"}], [SYNTH]]
    assert got["keys"] == [["ver:j", "ver:j:s1", "ver:j:s2"], [], True]


def test_encode_wav_takes_one_run_of_samples_or_a_list_of_channels():
    got = run(r"""
    const left = Float32Array.from([0, 0.5, -0.5, 1]), right = Float32Array.from([0.25, -0.25, 0, -1]);
    const stereo = importer.encodeWav([left, right], 48000, 16), mono = importer.encodeWav(left, 22050), listed = importer.encodeWav([left], 22050), dv = new DataView(stereo.buffer);
    out.header = [dv.getUint16(22, true), dv.getUint32(24, true), dv.getUint32(28, true), dv.getUint16(32, true), dv.getUint16(34, true), dv.getUint32(40, true), dv.getUint32(4, true), stereo.length];
    out.frames = [0, 1, 2, 3].map((i) => [dv.getInt16(44 + i * 4, true), dv.getInt16(46 + i * 4, true)]);
    out.mono = [mono.length, new DataView(mono.buffer).getUint16(22, true), new DataView(mono.buffer).getUint16(32, true), mono.every((b, i) => b === listed[i])];
    const deep = M.readWav(importer.encodeWav([left, right, left], 44100, 24));
    out.deep = [deep.rate, deep.bits, deep.chans.length, Array.from(deep.chans[1]).map((x) => Math.round(x * 1000) / 1000), Array.from(deep.chans[2]).map((x) => Math.round(x * 1000) / 1000)];
    out.uneven = M.readWav(importer.encodeWav([left, right.subarray(0, 2)], 48000)).chans.map((c) => c.length);
    out.empty = [importer.encodeWav(new Float32Array(0), 48000).length, importer.encodeWav([], 48000).length];
    out.plain = importer.encodeWav([0, 0.5], 8000).length; // a plain list of numbers is one channel, as before
    """)
    assert got["header"] == [2, 48000, 192000, 4, 16, 16, 52, 60]
    assert got["frames"] == [[0, 8191], [16383, -8191], [-16383, 0], [32767, -32767]]
    assert got["mono"] == [52, 1, 2, True]
    assert got["deep"] == [44100, 24, 3, [0.25, -0.25, 0, -1], [0, 0.5, -0.5, 1]]
    assert got["uneven"] == [2, 2] and got["empty"] == [44, 44] and got["plain"] == 48


def test_the_page_loads_the_store_and_calls_it_instead_of_its_old_save_code():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    order = [html.index('src="%s' % name) for name in ("synth.js", "importer.js", "measure.js", "store.js", "app.js")]
    assert order == sorted(order)
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    for gone in ("SAVE_DB", "savedAudio", "savedRefs", "indexedDB.open", "async function write()", "async function job()", "async function restore()", "function prune()"):
        assert gone not in app, gone
    for used in ("assetStore.create(", "store.guard(", "store.lock()", "store.restore()", "store.save()", "store.clear()", "store.ensureSound(", "store.importVersion(", "store.filled(", "store.bytes(",
                 "loadFailed:", "otherTab:"):
        assert used in app, used
    assert app.count("loadFailed:") == 2 and app.count("otherTab:") == 2  # both languages
    # the Korean lines are in the voice of the rest of that table, not in polite speech
    for key in ("loadFailed", "otherTab"):
        ko = re.findall(key + r": '([^']+)'", app)[1]
        assert re.search("[가-힣]", ko) and not re.search(r"(요|니다)([.~!?]|$)", ko), ko


def test_the_page_keeps_what_the_storage_changes_must_not_take_away():
    """What only the page can do, read from app.js: Node has no DOM to press these in."""
    app = (ROOT / "app.js").read_text(encoding="utf-8")
    # the first visit opens the tutorial unless the tab is view-only: also when the saved board could not be opened
    greet = app[app.index("function greet() {"):app.index("function tellFailed()")]
    assert "if (store.readOnly) return;" in greet and "store.writable" not in greet and "store.paused" not in greet
    # loadFailed is said once, after the tutorial if that is up
    told = app[app.index("function tellFailed() {"):app.index("function tookOver(result)")]
    assert told.count("toast(t('loadFailed')") == 1 and app.count("toast(t('loadFailed')") == 1
    assert "if (toldFailed) return;" in told and "dlg.addEventListener('close', tellFailed, { once: true })" in told
    # the export hands its zip over through a link the guard of a view-only tab lets through
    bundle = app[app.index("async function exportBundle() {"):app.index("/* ---------- game folder")]
    assert "el('a')" in bundle and bundle.index("link.download =") < bundle.index("link.click()")
    assert "a[download]" in guard_allow().split(", ")
    # "start again" asks the store, which also empties a board that could not be read. No save is left waiting to
    # write the old board back, and what is still being made is cancelled before the store is emptied.
    forget = app[app.index("async function forget() {"):app.index("/* ---------- host page")]
    assert "await store.clear()" in forget and forget.index("clearTimeout(saveTimer)") < forget.index("store.clear()")
    assert forget.index("gen.cancel(") < forget.index("store.clear()")
    # "start with an empty board" is that reset: what is the user's own is asked about first, the word for the next
    # visit is left only when the store was emptied, and only the tab that has the board reads it, over nothing saved
    blank = forget[forget.index("async function startBlank() {"):]
    assert blank.index("confirm(t('confirmBlank', n))") < blank.index("await forget()") < blank.index("location.reload()")
    assert "if (await forget()) { try { sessionStorage.setItem('asset-blank', '1'); }" in blank
    assert "if (store.writable && takeBlank() && result === 'empty') openBlank();" in app
    assert "takeBlank(); await forget(); location.reload();" in app  # "start again from samples" drops a word left over
    # a generated sound always shows its tracks: with no stems the master is the one track, and one track can be turned
    assert "const hasTracks = (v) => v.engine === 'nkido' || (v.sound ? v.sound.stems.length : (v.stems || []).length) > 1;" in app
    assert "const multi = hasTracks(v)" in app and "stemsTouched = (a, v) => openAsset === a && hasTracks(v) &&" in app


# ---------- a board kept in step with the server (docs/ASSET_SYNC_SPEC.md E2, E4) ----------

def test_a_named_store_opens_its_own_database_and_lock():
    got = run(r"""
    const opened = [], asked = [], fakes = new Map(), lines = new Map();
    // one IndexedDB and one lock per name, as a browser keeps them
    const idb = { open: (name, v) => { opened.push(name); if (!fakes.has(name)) fakes.set(name, fakeIdb()); return fakes.get(name).indexedDB.open(name, v); } };
    const locks = { request: (name, a, b) => { asked.push(name); if (!lines.has(name)) lines.set(name, fakeLocks()); return lines.get(name).request(name, a, b); } };
    const plainFake = { indexedDB: idb }, named = 'olmuse-asset-board.0123456789abcdef.0123456789ab';
    const one = await open(plainFake, locks), two = await open(plainFake, locks, { name: named });
    out.got = [one.got, two.got, one.store.name, two.store.name];
    out.names = [opened.slice(), asked.slice()];
    one.game = 'anon'; two.game = 'account';
    await one.store.save(); await two.store.save();
    out.apart = [fakes.get('olmuse-asset-board').board().game, fakes.get(named).board().game];
    // a second tab on the named board waits for that board only
    const three = await open(plainFake, locks, { name: named });
    out.third = [three.got, three.store.readOnly];
    """)
    named = "olmuse-asset-board.0123456789abcdef.0123456789ab"
    assert got["got"] == [True, True, "olmuse-asset-board", named]
    assert got["names"] == [["olmuse-asset-board", named], ["olmuse-asset-board", named]]
    assert got["apart"] == ["anon", "account"]
    assert got["third"] == [False, True]


def test_extra_keys_are_written_in_the_board_records_transaction_and_land_with_it_or_not_at_all():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks();
    let sync = { v: 1, cursor: 3 };
    const p = await open(fake, locks, { extra: () => ({ sync }) });
    p.game = 'one';
    out.first = [await p.store.saveBoard(), fake.log.map((t) => t.ops), fake.board('sync')];
    fake.fail.commit = () => new Error('disk');
    p.game = 'two'; sync = { v: 1, cursor: 9 };
    out.failed = [await p.store.save(), fake.board().game, fake.board('sync').cursor];
    fake.fail = {};
    out.after = [await p.store.save(), fake.board().game, fake.board('sync').cursor];
    // what was read comes back to the page with the record
    locks.release();
    const q = await open(fake, locks, { extra: () => ({ sync }) });
    out.info = q.info.sync;
    // a store without extra or remote hands nothing more to the page
    locks.release();
    const r = await open(fake, locks);
    out.plain = Object.keys(r.info).sort();
    """)
    assert got["first"] == [True, [["put board/board", "put board/sync"]], {"v": 1, "cursor": 3}]
    assert got["failed"] == [False, "one", 3]
    assert got["after"] == [True, "two", 9]
    assert got["info"] == {"v": 1, "cursor": 9}
    assert got["plain"] == ["dropped", "gameDir", "refetch"]


def test_sounds_the_server_holds_stay_without_local_bytes_and_are_fetched_and_kept_when_heard():
    got = run(r"""
    const seed = (fake) => fake.seed({ board: { v: 2, game: 'G', assets: [row('a', { versions: [nkido('x'), nkido('y')], current: 1 })], trash: [] }, sync: { v: 1, shadow: { 'asset/k': {} } } }, { 'ver:y': new Blob([wav([tone(480)])]) });
    // without remote: the version whose bytes are not here is taken off, as before
    const f1 = fakeIdb(); seed(f1);
    const p1 = await open(f1, fakeLocks());
    out.plain = [p1.assets[0].versions.map((v) => v.id), p1.info.dropped];
    // with remote: it stays, and the sync record it was judged by is the stored one
    const f2 = fakeIdb(), seen = [], fetched = [];
    seed(f2);
    const bytes = wav([tone(480, 220)]);
    const p2 = await open(f2, fakeLocks(), { remote: (sync) => { seen.push(sync); return new Set(['ver:x']); }, fetch: async (key) => { fetched.push(key); return key === 'ver:x' ? bytes : null; } });
    out.remote = [p2.assets[0].versions.map((v) => v.id), p2.info.dropped, seen];
    // heard: fetched once, kept on disk, and played
    const [one, two] = await Promise.all([p2.store.bytes('ver:x'), p2.store.bytes('ver:x')]);
    await settle(20);
    out.fetched = [fetched.slice(), one.length === bytes.length, two.length === bytes.length, f2.audioKeys(), p2.store.saved.has('ver:x')];
    out.again = [(await p2.store.bytes('ver:x')).length === bytes.length, fetched.length];
    out.sound = (await p2.store.ensureSound(p2.assets[0].versions[0], p2.assets[0])).channels;
    // local only, and a key the server does not have either
    const why = async (fn) => { try { await fn(); return 'ok'; } catch (e) { return 'thrown'; } };
    out.local = [await why(() => p2.store.bytes('ver:zz', { local: true })), await why(() => p2.store.bytes('ver:zz')), fetched.slice()];
    """)
    assert got["plain"] == [["y"], [{"asset": "a", "id": "x"}]]
    assert got["remote"] == [["x", "y"], [], [{"v": 1, "shadow": {"asset/k": {}}}]]
    assert got["fetched"] == [["ver:x"], True, True, ["ver:x", "ver:y"], True]
    assert got["again"] == [True, 1]
    assert got["sound"] == 1
    assert got["local"] == ["thrown", "thrown", ["ver:x", "ver:zz"]]


def test_while_pending_the_page_writes_nothing_and_takes_no_input_but_the_sync_engine_can_save():
    got = run(r"""
    const fake = fakeIdb(), locks = fakeLocks();
    let pending = true, sync = { pulled: false };
    const p = await open(fake, locks, { pending: () => pending, extra: () => ({ sync }) });
    p.game = 'page';
    out.page = [p.store.pending, p.store.writable, await p.store.save(), await p.store.saveBoard(), await p.store.put('gameDir', {}), await p.store.saveBlob('ver:a', new Blob(['a'])), fake.log.length];
    const heard = {}, blocked = [];
    p.store.guard({ addEventListener: (type, fn) => { heard[type] = fn; } }, { blocked: (e) => blocked.push(e.type) });
    const e = { type: 'click', target: { closest: () => null }, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.halted = true; } };
    heard.click(e);
    out.input = [!!e.prevented, blocked];
    // the engine writes what it received, with its record
    p.game = 'received'; sync = { pulled: true };
    out.engine = [await p.store.saveBoard({ sync: true }), fake.board().game, fake.board('sync')];
    pending = false;
    const e2 = { type: 'click', target: { closest: () => null }, preventDefault() { this.prevented = true; }, stopImmediatePropagation() { this.halted = true; } };
    heard.click(e2);
    p.game = 'typed';
    out.after = [p.store.writable, !!e2.prevented, await p.store.save(), fake.board().game];
    """)
    assert got["page"] == [True, False, False, False, False, False, 0]
    assert got["input"] == [True, ["click"]]
    assert got["engine"] == [True, "received", {"pulled": True}]
    assert got["after"] == [True, False, True, "typed"]


def test_an_accounts_board_never_prunes_versions_for_room():
    got = run(r"""
    const make = () => [row('a', { current: 2, versions: [legacy('l1', 1), legacy('l2', 2), legacy('l3', 3)] })];
    const count = (value) => value.assets.flatMap((x) => x.versions).length;
    const tryOne = async (extra) => {
      const fake = fakeIdb(), p = await open(fake, fakeLocks(), extra);
      p.assets = make();
      fake.fail.put = (store, key, value) => (key === 'board' && count(value) > 2 ? quota() : null);
      return [await p.store.save(), p.notes.slice(), p.assets[0].versions.map((v) => v.id)];
    };
    out.anon = await tryOne({});
    out.account = await tryOne({ extra: () => ({ sync: {} }) });
    """)
    assert got["anon"] == [True, ["pruned 1"], ["l2", "l3"]]
    assert got["account"] == [False, ["saveFull"], ["l1", "l2", "l3"]]
