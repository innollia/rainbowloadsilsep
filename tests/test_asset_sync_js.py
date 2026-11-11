"""The sync engine (sync.js) under Node: real store.js and board.js on an in-memory IndexedDB, and an in-memory board
server that answers the way docs/ASSET_SYNC_SPEC.md (C, D, F) says. The rules of E3 one by one, then a fault-injection
run (lost requests, lost answers, restarts from the last atomic save) and two computers through the contract's scenes."""
import json, pathlib, subprocess

ROOT = pathlib.Path(__file__).parents[1] / "studio_frontend" / "asset_studio"
FILES = ("data.js", "store.js", "board.js", "gen.js", "sync.js")

HELPERS = r"""
const S = window.assetStore, B = window.assetBoard, Y = window.assetSync, G = window.assetGen;
const nodeCrypto = require('crypto');
const sha = (u8) => nodeCrypto.createHash('sha256').update(u8).digest('hex');
const WHO = 'c0ffee00c0ffee00', clock = { t: 1700000000000 };
const settle = async (n = 30) => { for (let i = 0; i < n; i++) await new Promise((ok) => setImmediate(ok)); };

// IndexedDB in memory: a transaction runs its requests a macrotask after it opened and lands its writes together.
// fail.commit(ops) -> an Error aborts it.
function fakeIdb() {
  const stores = new Map(), fake = { stores, fail: {}, writes: 0 };
  const keep = (v) => (v instanceof Blob ? v : structuredClone(v));
  function transaction(names, mode) {
    names = [].concat(names);
    const q = { error: null, onerror: null, onabort: null, oncomplete: null }, todo = [], ops = [];
    q.objectStore = (name) => {
      const real = stores.get(name);
      const read = (key) => { for (let i = ops.length - 1; i >= 0; i--) { const o = ops[i]; if (o.store !== name) continue; if (o.op === 'clear') return undefined; if (o.key === key) return o.op === 'put' ? o.value : undefined; } return real.get(key); };
      const ask = (run) => { const r = { result: undefined, onsuccess: null, onerror: null }; todo.push([r, run]); return r; };
      return {
        put: (value, key) => ask(() => { ops.push({ store: name, op: 'put', key, value: keep(value) }); return key; }),
        delete: (key) => ask(() => { ops.push({ store: name, op: 'delete', key }); }),
        clear: () => ask(() => { ops.push({ store: name, op: 'clear' }); }),
        get: (key) => ask(() => { const v = read(key); return v === undefined ? undefined : keep(v); }),
        getKey: (key) => ask(() => (read(key) === undefined ? undefined : key)),
        getAllKeys: () => ask(() => [...real.keys()].sort()),
      };
    };
    setImmediate(() => {
      while (todo.length) { const [r, run] = todo.shift(); r.result = run(); if (r.onsuccess) r.onsuccess({ target: r }); }
      const e = ops.length && fake.fail.commit && fake.fail.commit(ops);
      if (e) { q.error = e; if (q.onabort) q.onabort({ target: q }); return; }
      for (const o of ops) { const s = stores.get(o.store); if (o.op === 'put') s.set(o.key, o.value); else if (o.op === 'delete') s.delete(o.key); else s.clear(); }
      if (ops.length) fake.writes++;
      if (q.oncomplete) q.oncomplete({ target: q });
    });
    return q;
  }
  fake.indexedDB = {
    open(name) {
      const r = { result: null, onsuccess: null, onerror: null, onupgradeneeded: null };
      setImmediate(() => { r.result = { name, createObjectStore: (n) => { stores.set(n, new Map()); }, transaction }; if (!stores.size && r.onupgradeneeded) r.onupgradeneeded({ target: r }); r.onsuccess({ target: r }); });
      return r;
    },
  };
  fake.get = (key) => stores.get('board')?.get(key);
  return fake;
}

// The board server of the spec in memory, one account. Faults: fault(call) -> 'request' (never arrives) or 'response'
// (done, answer lost). changesMax: rows per answer. down: nothing answers. lie: shas the blob check says it has.
function fakeServer() {
  const s = { epoch: 'e1', boards: new Map(), home: null, blobs: new Map(), jobs: new Map(), up: 500, t: 1700000000, changesMax: Infinity, fault: null, down: false, calls: [], proto: 1, bad: null, lie: new Set(), off: false };
  const ok = (data) => ({ status: 200, data, code: '', message: '', retry: 0 });
  const err = (status, code, extra = {}) => ({ status, data: { error: { code, message: code, ...extra } }, code, message: code, retry: extra.retry_after || 0 });
  const shasIn = (kind, data) => (data ? B.shasOf(kind, data).map((x) => x.sha).filter(Boolean) : []);
  const fresh = () => ({ head: 0, recs: new Map(), uses: new Set(), parts: new Map(), seen: new Map(), made: s.t });
  function sync(id, b, body) {
    if (body.v !== s.proto) return err(409, 'upgrade');
    b.seen.set(body.dev, s.t);
    const written = new Set(), results = [];
    for (const op of body.ops || []) {
      const key = op.kind + '/' + op.uid, row = b.recs.get(key), cur = row ? row.rev : 0;
      if (op.gone ? row && row.gone : row && !row.gone && B.canon(row.data) === B.canon(op.data)) { results.push({ same: cur }); continue; }
      if (op.base !== cur) { results.push({ conflict: { rev: cur, dev: row ? row.dev : null, gone: row ? row.gone : true, data: row ? row.data : null } }); continue; }
      if (!op.gone) {
        const had = new Set(row ? shasIn(op.kind, row.data) : []), need = shasIn(op.kind, op.data).filter((x) => !had.has(x) && !b.uses.has(x));
        if (need.length) { results.push({ need }); continue; }
        if (op.kind === 'asset' && row && row.data) { const ids = new Set(op.data.versions.map((v) => v.id)); if (row.data.versions.some((v) => !ids.has(v.id))) { results.push({ bad: 'versions' }); continue; } }
        const bad = s.bad && s.bad(op);
        if (bad) { results.push({ bad }); continue; }
      } else if (op.kind === 'asset' && !(row && row.data && row.data.trashedAt) && !op.uid.startsWith('s_')) { results.push({ bad: 'trash_first' }); continue; }
      const rev = ++b.head;
      b.recs.set(key, { kind: op.kind, uid: op.uid, rev, born: row ? row.born : rev, at: s.t, dev: body.dev, gone: !!op.gone, data: op.gone ? (row ? row.data : null) : structuredClone(op.data) });
      written.add(key); results.push({ rev, at: s.t });
    }
    const rows = [...b.recs.entries()].filter(([, r]) => r.rev > body.since).sort((p, q) => p[1].rev - q[1].rev), changes = [];
    let next = b.head, more = false, seen = body.since;
    for (const [key, r] of rows) {
      if (changes.length >= s.changesMax) { more = true; next = seen; break; }
      seen = r.rev;
      if (written.has(key)) continue;
      changes.push({ kind: r.kind, uid: r.uid, rev: r.rev, born: r.born, at: r.at, dev: r.dev, gone: r.gone, data: structuredClone(r.data) });
    }
    const peers = [...b.seen].filter(([dev]) => dev !== body.dev).map(([dev, t]) => ({ dev, age: s.t - t }));
    return ok({ epoch: s.epoch, now: s.t, up: s.up, head: b.head, next, more, peers, results, changes });
  }
  function handle(method, path, body) {
    if (s.off) return err(403, 'sync_off');
    const url = new URL('http://x' + path), parts = url.pathname.split('/').filter(Boolean);
    const json = typeof body === 'string' ? JSON.parse(body) : null;
    if (json && json.v !== undefined && json.v !== s.proto) return err(409, 'upgrade');
    if (parts[0] !== 'boards') return err(404, 'not_found');
    if (parts.length === 1 && method === 'GET') return ok({ epoch: s.epoch, home: s.home, boards: [...s.boards.keys()].map((id) => ({ id })) });
    if (parts.length === 1) {
      const id = json.board;
      if (s.boards.has(id)) return ok({ board: id, created: false, epoch: s.epoch });
      if (json.first && s.boards.size) return ok({ board: s.home, created: false, epoch: s.epoch });
      s.boards.set(id, fresh());
      if (json.home || !s.home) s.home = id;
      return ok({ board: id, created: true, epoch: s.epoch });
    }
    const id = parts[1], b = s.boards.get(id);
    if (!b) return err(404, 'no_board');
    if (parts[2] === 'open') { s.home = id; return ok({ home: id }); }
    if (parts[2] === 'sync') return sync(id, b, json);
    if (parts[2] === 'blobs' && parts.length === 3) {
      const part = {};
      for (const x of json.shas) if (b.parts.has(x)) part[x] = b.parts.get(x).length;
      return ok({ have: json.shas.filter((x) => (b.uses.has(x) && s.blobs.has(x)) || s.lie.has(x)), part });
    }
    const hash = parts[3];
    if (parts[4] === 'job') {
      const bytes = s.jobs.get(json.job + ':' + json.stem);
      if (!bytes || sha(bytes) !== hash) return err(404, 'not_found');
      s.blobs.set(hash, bytes); b.uses.add(hash);
      return ok({ done: true });
    }
    if (method === 'GET') return b.uses.has(hash) && s.blobs.has(hash) ? { status: 200, bytes: new Uint8Array(s.blobs.get(hash)), data: null, code: '' } : err(404, 'not_found');
    const at = +url.searchParams.get('at'), size = +url.searchParams.get('size'), had = b.parts.get(hash) || new Uint8Array(0);
    if (at !== had.length) return err(409, 'offset', { at: had.length });
    const now = new Uint8Array(had.length + body.length); now.set(had); now.set(body, had.length);
    if (now.length < size) { b.parts.set(hash, now); return ok({ at: now.length }); }
    b.parts.delete(hash);
    if (sha(now) !== hash) return err(400, 'bad_blob');
    s.blobs.set(hash, now); b.uses.add(hash);
    return ok({ done: true });
  }
  s.callFor = (dv) => async (method, path, body, opts) => {
    await null;
    const call = { dev: dv && dv.name, method, path, ops: null };
    if (typeof body === 'string') { try { const j = JSON.parse(body); call.ops = j.ops ? j.ops.length : null; call.body = j; } catch { /* raw */ } }
    s.calls.push(call);
    if (s.down) return { status: 0 };
    const f = s.fault ? s.fault(call) : null;
    if (f === 'request') return { status: 0 };
    const r = handle(method, path, body);
    if (f === 'response') return { status: 0 };
    return r;
  };
  // What the server holds of a board, the way a device's toRecords says it.
  s.records = (id) => Object.fromEntries([...s.boards.get(id).recs].filter(([, r]) => !r.gone).map(([k, r]) => [k, B.canon(r.data)]));
  s.board = (id) => s.boards.get(id);
  return s;
}

// The page around the engine: the live board (board.js's model), app.js's snapshot() and what a read record becomes.
function model() {
  const m = { assets: [], trash: [], cats: [{ id: 'ui', name: 'UI', kind: 'sfx', hue: '#1' }], refs: [], dynamics: [], agentLog: [],
    vals: { game: 'Moon', brief: '', platform: 'mobile', loud: [-20, -14], demo: false, stage: 'sample', idRule: { pattern: '{name}', sep: '_' }, exportOpts: { format: 'wav' } } };
  m.get = (k) => m.vals[k]; m.set = (k, v) => { m.vals[k] = v; };
  m.makeId = (name, cat, taken) => { const base = String(name).toLowerCase().replace(/[^a-z0-9]+/g, '_') || cat; let id = base, k = 2; while (taken.has(id)) id = base + '_' + k++; taken.add(id); return id; };
  m.fitCat = (id) => (m.cats.find((c) => c.id === id) || m.cats[0]).id;
  return m;
}
function keptOf(a, binned) {
  const kept = !binned && (a.status === 'review' || !!a.work);
  const status = (a.status === 'working' || a.status === 'review') && !kept ? (a.versions.length ? 'draft' : 'pending') : a.status;
  return { status, versions: a.versions, drafts: kept ? a.drafts : [], pick: kept ? a.pick : -1 };
}
function snap(m) {
  const one = (binned) => (a) => { const { versions, drafts, source, progress, ...rest } = a, kept = keptOf(a, binned); return { ...rest, status: kept.status, versions: kept.versions.map(S.record), drafts: kept.drafts.map(S.record), pick: kept.pick, hasSource: false }; };
  const v = m.vals;
  return { v: 2, game: v.game, brief: v.brief, platform: v.platform, demo: v.demo, stage: v.stage, loud: [...v.loud], cats: m.cats, idRule: v.idRule, exportOpts: v.exportOpts, projectRefs: m.refs,
    agentLog: [], trash: m.trash.map(one(true)), dynamics: m.dynamics.map((d) => ({ ...d, params: d.params.map((p) => ({ ...p })) })), assets: m.assets.map(one(false)) };
}
function applyTo(m, data) {
  const open = (x) => { const { hasSource, ...a } = x; a.progress = 0; a.versions ||= []; a.drafts ||= []; return a; };
  m.assets.splice(0, m.assets.length, ...data.assets.map(open)); m.trash.splice(0, m.trash.length, ...(data.trash || []).map(open));
  m.cats.splice(0, m.cats.length, ...(data.cats || [])); m.refs.splice(0, m.refs.length, ...(data.projectRefs || [])); m.dynamics.splice(0, m.dynamics.length, ...(data.dynamics || []));
  for (const k of ['game', 'brief', 'platform', 'loud', 'demo', 'stage', 'idRule', 'exportOpts']) if (data[k] !== undefined) m.vals[k] = data[k];
}
const sound = (key, more = {}) => ({ key, id: 'sfx_' + key, name: 'Sound ' + key, cat: 'ui', music: false, loop: false, layers: [], status: 'pending', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0, ...more });
const version = (id, bytes, more = {}) => ({ id, at: clock.t, note: null, engine: 'import', job: null, parent: null, draft: null, source: null, seconds: 1, bpm: null, prompt: null, model: null, sources: [], measure: {}, issues: [], peaks: [],
  key: 'ver:' + id, stems: [], rate: 48000, channels: 1, bits: 16, bytes: bytes.length, sha256: sha(bytes), ...more });
const bytesOf = (n, seed = 1) => Uint8Array.from({ length: n }, (_, i) => (i * 31 + seed * 7) % 251);

// One computer: its own IndexedDB, the real store, a page model, and an engine. sync: the record its database starts
// with (a new database), or what the database holds (a reopened one).
async function device(srv, name, o = {}) {
  const dv = { name, fake: o.fake || fakeIdb(), m: model(), toasts: [], draws: 0, trashed: [], moved: [], busy: false, engine: null };
  dv.snapshot = () => snap(dv.m);
  const keys = () => { const want = new Map(); for (const a of [...dv.m.assets, ...dv.m.trash]) for (const v of [...a.versions, ...a.drafts]) for (const k of S.versionKeys(v)) want.set(k, null); return want; };
  dv.store = S.create({ indexedDB: dv.fake.indexedDB, now: () => clock.t, snapshot: dv.snapshot, keys, assets: () => dv.m.assets,
    apply: (data, buffers, info) => { applyTo(dv.m, data); dv.info = info; },
    extra: () => (dv.engine ? dv.engine.extra() : {}), remote: B.remoteKeys, fetch: (k) => dv.engine.fetch(k), pending: () => !!dv.engine && dv.engine.pending });
  await dv.store.lock();
  dv.result = await dv.store.restore();
  if (o.setup) o.setup(dv);
  const record = (dv.info && dv.info.sync) || o.sync || Y.record({ who: WHO, board: o.board || Y.newBoard(), made: !!o.made, make: o.make || { first: true, home: true }, seed: o.seed ?? null, random: o.random });
  dv.engine = Y.create({ store: dv.store, call: o.call || srv.callFor(dv), identity: () => (o.identity ? o.identity() : { kind: 'acct', who: WHO }), sync: record, snapshot: dv.snapshot, model: () => dv.m,
    quiet: () => !dv.busy, redraw: () => { dv.draws++; }, lost: (i) => dv.toasts.push(i.what + (i.name ? ':' + (typeof i.name === 'string' ? i.name : JSON.stringify(i.name)) : '')),
    onTrash: (list) => dv.trashed.push(...list.map((a) => a.key)), moved: (x) => dv.moved.push(x.board), hidden: () => false,
    sha256: async (u8) => sha(u8), now: () => clock.t, setTimeout: (fn, ms) => { setImmediate(fn); return 1; }, clearTimeout: () => {}, upload: o.upload });
  dv.tick = async () => { await dv.engine.tick(); await settle(); };
  dv.save = () => dv.store.save();
  // a sound brought in here: its bytes are held by the store until the next save
  dv.bring = (key, n = 3000, seed = 1, more = {}) => { const u8 = bytesOf(n, seed), v = version('v' + key, u8); dv.store.hold(v.key, new Blob([u8])); const a = sound(key, { status: 'approved', versions: [v], ...more }); dv.m.assets.push(a); return a; };
  dv.records = () => Object.fromEntries([...B.toRecords(dv.snapshot())].map(([k, d]) => [k, B.canon(d)]));
  dv.find = (key) => dv.m.assets.find((a) => a.key === key) || dv.m.trash.find((a) => a.key === key);
  return dv;
}
// The same computer after a reload: what its database holds, nothing in memory.
const reopen = (srv, dv, o = {}) => device(srv, dv.name, { ...o, fake: dv.fake });
const sorted = (o) => JSON.stringify(Object.entries(o).sort(([p], [q]) => (p < q ? -1 : p > q ? 1 : 0)));
const same = (srv, board, ...dvs) => { const want = sorted(srv.records(board)); return dvs.every((dv) => sorted(dv.records()) === want); };
const syncCalls = (srv, dev) => srv.calls.filter((c) => c.path.endsWith('/sync') && (!dev || c.dev === dev));
// Ticks every device until nothing is left to send anywhere (or gives up).
async function converge(srv, dvs, rounds = 12) { for (let i = 0; i < rounds; i++) { for (const dv of dvs) await dv.tick(); if (dvs.every((dv) => dv.engine.status().changes === 0)) { for (const dv of dvs) await dv.tick(); return true; } } return false; }
// A real board on device A: two sounds and a group, sent up.
async function started(srv, name = 'A') {
  const a = await device(srv, name);
  a.m.assets.push(sound('k1', { name: 'Door' }), sound('k2', { name: 'Bell' }));
  await a.save(); await a.tick();
  return a;
}
// A computer joining the board that is on the server: an empty database bound to it, as the page makes one.
const joiner = (srv, board, name = 'B') => device(srv, name, { board, made: true, make: { first: false, home: false } });
"""


def node(script, timeout=240):
    out = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    assert out.returncode == 0, out.stderr[-4000:]
    return json.loads(out.stdout)


def run(body, timeout=240):
    src = "globalThis.window = globalThis;\n" + "\n".join((ROOT / f).read_text(encoding="utf-8") for f in FILES) + HELPERS
    return node(src + "\n(async () => {\nconst out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n})().catch((e) => { console.error(e); process.exit(1); });", timeout)


def test_smoke_a_board_goes_up_and_a_second_computer_receives_it():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv);
    const id = a.engine.record.board;
    out.a = [a.engine.record.made, a.engine.record.pulled, Object.keys(srv.records(id)).sort()];
    const b = await joiner(srv, id);
    out.pending = [b.engine.pending, b.store.writable];
    const head = srv.board(id).head;
    await b.tick();
    out.b = [b.engine.pending, b.m.assets.map((x) => x.key), b.m.vals.game, srv.board(id).head === head, same(srv, id, a, b), b.toasts];
    """)

    assert got["a"][0] and got["a"][1]
    assert got["b"][0] is False and got["b"][1] == ["k1", "k2"] and got["b"][3] and got["b"][4]


def test_it_receives_before_it_sends_and_an_echo_of_a_lost_answer_does_not_undo_a_later_edit():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board, b = await joiner(srv, id);
    await b.tick();
    // B renames, A edits another sound: A's round asks first (no ops), then sends
    b.find('k1').name = 'From B'; await b.save(); await b.tick();
    a.find('k2').loop = true; await a.save();
    const from = srv.calls.length;
    await a.tick();
    out.order = srv.calls.slice(from).filter((c) => c.path.endsWith('/sync')).map((c) => c.ops);
    out.got = a.find('k1').name;
    // the answer to A's rename is lost; A renames again before the next round; the echo of the first does not win
    a.find('k1').name = 'one'; await a.save();
    srv.fault = (c) => (c.dev === 'A' && c.ops ? 'response' : null);
    await a.tick();
    srv.fault = null;
    a.find('k1').name = 'two'; await a.save();
    await a.tick(); await b.tick();
    out.after = [a.find('k1').name, b.find('k1').name, a.toasts, same(srv, id, a, b)];
    """)
    assert got["order"] == [0, 1]
    assert got["got"] == "From B"
    assert got["after"] == ["two", "two", [], True]


def test_a_round_whose_save_never_landed_is_sent_again_after_the_reload_and_ends_the_same():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    a.find('k1').name = 'Renamed'; a.m.cats.push({ id: 'forest', name: 'Forest', kind: 'amb', hue: '#2' }); await a.save();
    // the request reaches the server, then the computer goes away before its record and shadow are written
    a.fake.fail.commit = (ops) => (ops.some((o) => o.key === 'sync') ? new Error('gone') : null);
    await a.tick();
    const head = srv.board(id).head;
    a.engine.stop(); a.fake.fail = {};
    const again = await reopen(srv, a);
    out.reopened = [again.find('k1').name, again.engine.record.shadow['cat/forest'] === undefined];
    await again.tick();
    out.after = [srv.board(id).head - head, same(srv, id, again), again.engine.status().changes, again.toasts];
    """)
    assert got["reopened"] == ["Renamed", True]
    assert got["after"] == [0, True, 0, []]  # sent again, answered as the same, nothing new on the server


def test_no_record_goes_up_before_its_bytes_and_a_need_sends_them_again():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    const s = a.bring('k3', 2500000, 3); await a.save();
    // the second piece of the upload is lost: the record waits
    let n = 0;
    srv.fault = (c) => (c.path.includes('/blobs/') && ++n === 2 ? 'request' : null);
    const from = srv.calls.length;
    await a.tick();
    const first = srv.calls.slice(from);
    out.first = [first.map((c) => (c.path.includes('/blobs/') ? 'chunk ' + c.path.split('?')[1] : c.path.endsWith('/blobs') ? 'blobs' : c.ops)), !!srv.records(id)['asset/k3']];
    srv.fault = null;
    const from2 = srv.calls.length;
    await a.tick();
    out.second = [srv.calls.slice(from2).map((c) => (c.path.includes('/blobs/') ? 'chunk ' + c.path.split('?')[1] : c.path.endsWith('/blobs') ? 'blobs' : c.ops)), !!srv.records(id)['asset/k3']];
    // the server says it has bytes it does not (a lie in the check): the write comes back with need and they go again
    const t = a.bring('k4', 1000, 4); await a.save();
    srv.lie.add(t.versions[0].sha256);
    await a.tick();
    out.need = !!srv.records(id)['asset/k4'];
    srv.lie.clear();
    await a.tick();
    out.after = [!!srv.records(id)['asset/k4'], srv.blobs.has(t.versions[0].sha256), same(srv, id, a)];
    // B hears it: the bytes come from the board's store and are kept
    const b = await joiner(srv, id); await b.tick();
    const u8 = await b.store.bytes('ver:vk3');
    out.heard = [u8.length, sha(u8) === s.versions[0].sha256];
    """)
    assert got["first"][0][:4] == [0, "blobs", "chunk at=0&size=2500000", "chunk at=1000000&size=2500000"]
    assert all(x != 1 for x in got["first"][0][1:]) and got["first"][1] is False  # no record with it
    assert got["second"][0] == [0, "blobs", "chunk at=1000000&size=2500000", "chunk at=2000000&size=2500000", 1] and got["second"][1] is True  # it went on where it left off
    assert got["need"] is False and got["after"] == [True, True, True]
    assert got["heard"] == [2500000, True]


def test_a_sound_gone_from_the_page_comes_back_in_the_trash_and_only_purge_deletes():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    // a sound dropped from the lists without being deleted for good
    a.m.assets.splice(a.m.assets.findIndex((x) => x.key === 'k1'), 1); await a.save();
    await a.tick();
    out.back = [a.m.trash.map((x) => x.key), !!JSON.parse(srv.records(id)['asset/k1']).trashedAt, srv.board(id).recs.get('asset/k1').gone];
    // deleted for good from the trash: gone
    a.engine.purge(['k1']); a.m.trash.splice(0); await a.save();
    await a.tick();
    out.purged = [srv.board(id).recs.get('asset/k1').gone, a.m.trash.length];
    // a purge of a sound that is not in the trash on the server: the server asks for the trash first
    a.engine.purge(['k2']); a.m.assets.splice(a.m.assets.findIndex((x) => x.key === 'k2'), 1); await a.save();
    await a.tick(); await a.tick();
    out.notTrashed = [srv.board(id).recs.get('asset/k2').gone, a.m.trash.map((x) => x.key), !!JSON.parse(srv.records(id)['asset/k2']).trashedAt, same(srv, id, a)];
    // a group, a reference and a dynamic sound that are gone from the page are deleted
    a.m.cats.push({ id: 'x', name: 'X', kind: 'sfx', hue: '#3' }); a.m.refs.push({ id: 'r1', kind: 'text', note: 'n' }); a.m.dynamics.push({ id: 'dyn_a', name: 'D', params: [], layers: [] });
    await a.save(); await a.tick();
    a.m.cats.pop(); a.m.refs.pop(); a.m.dynamics.pop(); await a.save(); await a.tick();
    out.others = ['cat/x', 'ref/r1', 'dyn/dyn_a'].map((k) => srv.board(id).recs.get(k).gone);
    """)
    assert got["back"] == [["k1"], True, False]
    assert got["purged"] == [True, 0]
    assert got["notTrashed"] == [False, ["k2"], True, True]
    assert got["others"] == [True, True, True]


def test_requests_go_in_the_order_the_server_must_see_and_deletes_go_last():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    a.m.assets.push(...Array.from({ length: 450 }, (_, i) => sound('n' + i)));
    a.m.cats.push({ id: 'kid', name: 'Kid', kind: 'sfx', hue: '#1', parent: 'mum' }, { id: 'mum', name: 'Mum', kind: 'sfx', hue: '#2' });
    a.m.cats.splice(0, 1); // 'ui' deleted
    a.m.vals.game = 'Renamed';
    await a.save();
    const from = srv.calls.length;
    await a.tick();
    const sent = srv.calls.slice(from).filter((c) => c.path.endsWith('/sync') && c.ops).map((c) => c.body.ops.map((o) => (o.gone ? 'gone ' : '') + o.kind + '/' + o.uid));
    out.sizes = sent.map((x) => x.length);
    out.head = sent[0].slice(0, 3);
    out.lastHasGone = sent[sent.length - 1].filter((x) => x.startsWith('gone')).length;
    out.goneElsewhere = sent.slice(0, -1).flat().filter((x) => x.startsWith('gone')).length;
    // the sounds of the deleted group were moved by the repair: that goes up next round
    await a.tick();
    out.same = same(srv, id, a) && a.m.assets.every((x) => x.cat !== 'ui');
    """)
    assert got["sizes"] == [400, 54]  # meta, two groups, 452 sounds = 455 writes, then the delete
    assert got["head"] == ["meta/game", "cat/mum", "cat/kid"]  # the parent before the child
    assert got["lastHasGone"] == 1 and got["goneElsewhere"] == 0 and got["same"]


def test_repairs_wait_until_nothing_more_is_coming_and_the_first_receiving_is_held_and_ordered():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    a.m.assets.push(sound('k3', { id: 'sfx_door', name: 'Door' }), sound('k4', { id: 'sfx_door', name: 'Door' }));
    await a.save(); await a.tick();
    srv.changesMax = 1;
    const b = await joiner(srv, id);
    // the page made a sample board before anything came: dropped once the board is received
    b.m.assets.push(sound('s_sample', { sample: true }));
    const made = [], ready = [];
    b.m.makeId = ((orig) => (name, cat, taken) => { made.push(b.engine.record.cursor === srv.board(id).head); return orig(name, cat, taken); })(b.m.makeId);
    b.engine.ready().then(() => ready.push(b.engine.record.cursor));
    out.before = [b.engine.pending, b.store.writable];
    const headBefore = srv.board(id).head;
    await b.tick();
    out.after = [b.engine.pending, made, ready, headBefore, b.m.assets.map((x) => x.key), b.m.assets.map((x) => x.id)];
    await b.tick(); await a.tick();
    out.same = same(srv, id, a, b);
    """)
    assert got["before"] == [True, False]
    pending, made, ready, head, keys, ids = got["after"]
    assert pending is False and made == [True] and ready == [head]
    assert keys == ["k1", "k2", "k3", "k4"]  # the server's order, the sample gone
    assert ids[2] == "sfx_door" and ids[3] != "sfx_door"
    assert got["same"]


def test_a_server_back_from_a_backup_is_received_again_and_this_computers_values_win():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    const old = structuredClone([...srv.board(id).recs]), oldHead = srv.board(id).head;
    a.find('k1').name = 'After backup'; a.find('k2').versions.push(version('vx', bytesOf(10))); a.store.hold('ver:vx', new Blob([bytesOf(10)])); a.find('k2').status = 'draft';
    await a.save(); await a.tick();
    // the server's database goes back to the old file: another epoch, an older head
    srv.board(id).recs = new Map(old); srv.board(id).head = oldHead; srv.epoch = 'e2'; srv.board(id).uses.clear();
    await a.tick(); await a.tick();
    out.after = [a.engine.record.epoch, JSON.parse(srv.records(id)['asset/k1']).name, JSON.parse(srv.records(id)['asset/k2']).versions.map((v) => v.id), same(srv, id, a), a.engine.status().changes];
    """)
    assert got["after"] == ["e2", "After backup", ["vx"], True, 0]


def test_a_database_with_a_sync_record_but_no_board_sends_nothing_and_a_new_database_waits_for_the_board():
    got = run(r"""
    const srv = fakeServer(), a = await device(srv, 'A');
    // a record but no board saved yet: a blank screen must not go up as "everything deleted"
    a.engine.record.shadow['asset/k9'] = { rev: 3, born: 3, dev: 'x', json: B.canon({ name: 'x', versions: [] }) };
    await a.tick();
    out.calls = srv.calls.length;
    """)
    assert got["calls"] == 0


def test_while_a_field_is_held_only_records_that_held_still_go_and_drawing_waits():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board, b = await joiner(srv, id);
    await b.tick();
    a.busy = true;
    a.find('k1').name = 'typing'; a.find('k2').loop = true; await a.save();
    await a.tick();  // nothing held still yet
    out.first = [JSON.parse(srv.records(id)['asset/k1']).name, JSON.parse(srv.records(id)['asset/k2']).loop];
    a.find('k1').name = 'typing more'; await a.save();
    await a.tick();  // k2 held still since the last round; k1 did not
    out.second = [JSON.parse(srv.records(id)['asset/k1']).name, JSON.parse(srv.records(id)['asset/k2']).loop];
    // what B changes reaches A's data at once; drawing waits until the field is let go
    b.find('k2').description = 'from B'; await b.save(); await b.tick();
    const draws = a.draws;
    await a.tick();
    out.data = [a.find('k2').description, a.draws - draws];
    a.busy = false; await settle(200); await new Promise((ok) => setTimeout(ok, 30)); await settle();
    out.drawn = a.draws - draws > 0;
    await a.tick();
    out.last = [JSON.parse(srv.records(id)['asset/k1']).name, same(srv, id, a)];
    """)
    assert got["first"] == ["Door", False]
    assert got["second"] == ["Door", True]
    assert got["data"] == ["from B", 0] and got["drawn"]
    assert got["last"] == ["typing more", True]


def test_the_echo_of_this_computers_write_says_nothing_and_a_lost_same_field_edit_says_so():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board, b = await joiner(srv, id);
    await b.tick();
    srv.fault = (c) => (c.dev === 'A' && c.ops ? 'response' : null);
    a.find('k1').name = 'mine'; await a.save(); await a.tick();
    srv.fault = null;
    await a.tick();
    out.echo = [a.toasts, a.find('k1').name];
    // both change the same field: the first to arrive stays, the other is told
    a.find('k2').name = 'A wins'; await a.save(); await a.tick();
    b.find('k2').name = 'B loses'; await b.save(); await b.tick();
    out.lost = [b.find('k2').name, b.toasts];
    """)
    assert got["echo"] == [[], "mine"]
    assert got["lost"] == ["A wins", ["syncLost:B loses"]]


def test_upgrade_stops_with_a_toast_and_sync_off_stops_quietly():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv);
    srv.proto = 2;
    a.find('k1').name = 'x'; await a.save(); await a.tick();
    out.old = [a.toasts, a.engine.state, a.engine.status().state];
    const srv2 = fakeServer(), b = await started(srv2, 'B');
    srv2.off = true;
    let readied = false;
    b.find('k1').name = 'y'; await b.save(); await b.tick();
    await b.engine.ready().then(() => { readied = true; });
    out.off = [b.toasts, b.engine.state, readied, await b.engine.claim([b.find('k1')])];
    """)
    assert got["old"] == [["syncOld"], "old", "off"]
    assert got["off"] == [[], "off", True, True]  # a visit with sync off makes sounds as before


def test_what_fit_cut_is_not_sent_again_and_refused_records_are_kept_and_not_resent_until_they_change():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    const k1 = a.find('k1');
    for (let i = 0; i < 3; i++) k1.versions.push({ id: 'old' + i, at: i, note: null, change: {}, engine: 'legacy', sources: [], prompt: 'x'.repeat(500000) });
    k1.current = 0; k1.status = 'draft';
    await a.save(); await a.tick();
    const n = syncCalls(srv, 'A').length;
    await a.tick();
    out.fit = [!!srv.records(id)['asset/k1'], syncCalls(srv, 'A').slice(n).map((c) => c.ops), a.engine.status().changes];
    // a record the server will not store (bad text): kept here, told once, not sent again until it changes
    srv.bad = (op) => (op.uid === 'k2' ? 'text' : null);
    a.find('k2').name = 'bad'; await a.save(); await a.tick();
    const m = syncCalls(srv, 'A').length;
    await a.tick();
    out.bad = [a.find('k2').name, a.toasts, syncCalls(srv, 'A').slice(m).map((c) => c.ops), a.engine.status()];
    srv.bad = null;
    a.find('k2').name = 'good'; await a.save(); await a.tick();
    out.good = [JSON.parse(srv.records(id)['asset/k2']).name, a.engine.status().state];
    """)
    assert got["fit"] == [True, [0], 0]
    assert got["bad"][0] == "bad" and got["bad"][1] == ["syncLost:bad"] and got["bad"][2] == [0]
    assert got["bad"][3]["state"] == "sending" and got["bad"][3]["blocked"] == 1  # not "synced" while something is refused
    assert got["good"] == ["good", "synced"]


def test_versions_dropped_here_go_back_in_and_the_other_edits_stay():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    a.bring('k5', 100, 5); const s = a.find('k5'); const v2 = version('w2', bytesOf(50, 6)); s.versions.push(v2); a.store.hold(v2.key, new Blob([bytesOf(50, 6)]));
    await a.save(); await a.tick();
    // the second version's bytes went missing here (mend took it off) and the sound was renamed
    s.versions.splice(1, 1); s.name = 'Renamed';
    await a.save(); await a.tick();
    out.local = [s.versions.map((v) => v.id), s.name];
    await a.tick();
    const rec = JSON.parse(srv.records(id)['asset/k5']);
    out.server = [rec.versions.map((v) => v.id), rec.name, same(srv, id, a)];
    """)
    assert got["local"] == [["vk5", "w2"], "Renamed"]
    assert got["server"] == [["vk5", "w2"], "Renamed", True]


def test_an_untouched_sample_board_never_goes_up_and_one_with_work_does():
    got = run(r"""
    const srv = fakeServer();
    const a = await device(srv, 'A', { seed: 'sample', make: { first: false, home: false } });
    a.m.vals.demo = true;
    a.m.assets.push(sound('s_click', { sample: true, versions: [{ id: 'sv_s_click', at: 1, note: null, change: {}, engine: 'legacy', sources: [] }] }));
    await a.save();
    a.find('s_click').name = 'Renamed sample'; await a.save(); // a rename keeps it a sample board (pristine)
    await a.tick();
    out.sample = [srv.calls.length, a.engine.pending, (await a.engine.flush(100)).ok];
    a.m.assets.push(sound('k1')); await a.save(); await a.tick();
    out.work = [srv.calls[0].path, srv.calls[0].body.home, srv.boards.size, srv.home];
    """)
    assert got["sample"] == [0, False, True]
    assert got["work"] == ["/boards", False, 1, got["work"][3]]


def test_switching_boards_waits_for_what_is_left_to_send():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv);
    a.find('k1').name = 'x'; await a.save();
    srv.down = true;
    clock.t += 30000;
    out.down = await a.engine.flush(5000);
    srv.down = false;
    out.up = await a.engine.flush(5000);
    """)
    assert got["down"] == {"ok": False, "reason": "syncOff"}
    assert got["up"] == {"ok": True, "reason": ""}


def test_a_board_kept_apart_goes_up_whole_by_an_engine_that_only_sends():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), home = a.engine.record.board;
    // another computer with real work of its own meets an account that already has a board
    const l = await device(srv, 'L');
    l.bring('kl', 1500000, 9); l.m.cats.push({ id: 'mine', name: 'Mine', kind: 'sfx', hue: '#5' }); await l.save();
    await l.tick();
    out.moved = [l.moved, l.engine.state, l.engine.record.made, l.engine.record.make, srv.boards.size];
    l.engine.stop();
    // the page opens home; this database goes up by itself, as a board of its own
    const up = await reopen(srv, l, { upload: true });
    let finished = false;
    up.engine.done().then(() => { finished = true; });
    await up.tick(); await up.tick();
    const mine = up.engine.record.board;
    out.after = [finished, srv.boards.size, srv.home === home, mine !== home, same(srv, mine, up), syncCalls(srv, 'L').every((c) => c.ops > 0)];
    """)
    assert got["moved"][0] and got["moved"][1] == "stopped" and got["moved"][2] is False and got["moved"][3] == {"first": False, "home": False} and got["moved"][4] == 1
    assert got["after"] == [True, 2, True, True, True, True]  # nothing received, everything sent, home unchanged


def test_the_pointer_lost_the_newest_database_of_the_account_is_found_by_listing_them():
    got = run(r"""
    const dbs = new Map();
    const idb = { open: (name) => { if (!dbs.has(name)) dbs.set(name, fakeIdb()); return dbs.get(name).indexedDB.open(name); }, databases: async () => [...dbs.keys()].map((name) => ({ name, version: 1 })) };
    const put = async (name, sync) => { const f = fakeIdb(); dbs.set(name, f); const st = S.create({ indexedDB: f.indexedDB, name, snapshot: () => ({ v: 2, assets: [] }), apply: () => {}, extra: () => (sync ? { sync } : {}) }); await st.lock(); await st.restore(); await st.saveBoard(); };
    await put('olmuse-asset-board', null);
    await put(Y.dbName(WHO, 'a'.repeat(32)), { v: 1, who: WHO, at: 5 });
    await put(Y.dbName(WHO, 'b'.repeat(32)), { v: 1, who: WHO, at: 9 });
    await put(Y.dbName('ffffffffffffffff', 'c'.repeat(32)), { v: 1, who: 'ffffffffffffffff', at: 99 });
    out.found = (await Y.scan(idb, WHO)).map((x) => x.name);
    out.none = await Y.scan({ open: idb.open }, WHO);
    const ls = new Map(), store = { getItem: (k) => (ls.has(k) ? ls.get(k) : null), setItem: (k, v) => ls.set(k, v) };
    out.pointer = [Y.pointer.read(store), Y.pointer.write(store, { anon: 'olmuse-asset-board', accts: { [WHO]: { db: out.found[0] } } }), Y.pointer.read(store)];
    out.names = [Y.dbName(WHO, 'b'.repeat(32)), /^olmuse-asset-board\.c0ffee00c0ffee00\.d[0-9a-f]{6}$/.test(Y.sampleName(WHO)), /^[0-9a-f]{32}$/.test(Y.newBoard()), /^[0-9a-f]{16}$/.test(Y.newDev())];
    """)
    assert got["found"] == ["olmuse-asset-board.c0ffee00c0ffee00.bbbbbbbbbbbb", "olmuse-asset-board.c0ffee00c0ffee00.aaaaaaaaaaaa"]
    assert got["none"] is None
    assert got["pointer"][0] is None and got["pointer"][1] is True
    assert got["pointer"][2] == {"v": 1, "anon": "olmuse-asset-board", "accts": {"c0ffee00c0ffee00": {"db": got["found"][0]}}}
    assert got["names"] == ["olmuse-asset-board.c0ffee00c0ffee00.bbbbbbbbbbbb", True, True, True]


def test_the_first_computers_board_in_the_default_database_is_found_again_after_signing_back_in():
    got = run(r"""
    const dbs = new Map();
    const idb = { open: (name) => { if (!dbs.has(name)) dbs.set(name, fakeIdb()); return dbs.get(name).indexedDB.open(name); }, databases: async () => [...dbs.keys()].map((name) => ({ name, version: 1 })) };
    const put = async (name, sync) => { const f = fakeIdb(); dbs.set(name, f); const st = S.create({ indexedDB: f.indexedDB, name, snapshot: () => ({ v: 2, assets: [] }), apply: () => {}, extra: () => (sync ? { sync } : {}) }); await st.lock(); await st.restore(); await st.saveBoard(); };
    // bindHere(who, null) kept the account's first board in the database the page always had
    await put('olmuse-asset-board', { v: 1, who: WHO, at: 7 });
    await put('olmuse-asset-board.anon0a0b0c', null);
    await put('olmuse-asset-boardx', { v: 1, who: WHO, at: 99 });
    out.found = (await Y.scan(idb, WHO)).map((x) => x.name);
    """)
    assert got["found"] == ["olmuse-asset-board"]


def test_work_is_picked_up_only_after_the_first_receiving_and_a_record_without_dev_or_of_another_computer_is_left_alone():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board;
    const b = await joiner(srv, id); await b.tick();
    const who = sha(Buffer.from('acct:me')).slice(0, 16);
    const job = (dev, request, jobs) => ({ request, kind: 'acct', who, ...(dev ? { dev } : {}), mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs });
    // B started making k1, then A took it over (the server's record now names A); k2's record has no dev at all
    b.find('k1').status = 'working'; b.find('k1').work = job(b.engine.record.dev, 'r1', [{ id: 'j1', k: 1, got: false }]);
    await b.save(); await b.tick();
    a.engine.record && await a.tick();
    a.find('k1').work.dev = a.engine.record.dev; a.find('k2').status = 'working'; a.find('k2').work = job(null, 'r2', [{ id: 'j2', k: 1, got: false }]);
    await a.save(); await a.tick();
    // B comes back with its old copy; its generator gets a token before the first round
    b.engine.stop();
    const b2 = await reopen(srv, b), asked = [];
    const gen = G.create({ store: b2.store, assets: () => b2.m.assets, fetch: async (url, init) => { asked.push(init.method + ' ' + url.replace('https://api.test/api/asset', '')); return { status: 200, headers: { get: () => null }, json: async () => ({ jobs: [], unit: 1, free: false }) }; },
      now: () => 0, wall: () => clock.t, setTimeout: (fn) => { setImmediate(fn); return 1; }, clearTimeout: () => {}, sha256: async (u8) => sha(u8),
      dev: () => b2.engine.record.dev, ready: () => b2.engine.ready() });
    const token = Buffer.from(JSON.stringify({ kind: 'acct', sub: 'acct:me' })).toString('base64url') + '.sig';
    await gen.token({ token, ttl: 900, api: 'https://api.test/api/asset' }); await settle();
    out.before = [asked.filter((x) => x.includes('/jobs')), b2.find('k1').work.dev === b2.engine.record.dev];
    await b2.tick(); await settle(100);
    out.after = [asked.filter((x) => x.includes('/jobs')), b2.find('k1').work.dev === a.engine.record.dev, gen.free(b2.find('k1')), gen.free(b2.find('k2'))];
    """)
    assert got["before"] == [[], True]
    assert got["after"] == [[], True, False, False]


def test_two_claims_on_one_sound_one_wins_and_the_other_hears_it_is_taken_and_a_trash_from_elsewhere_is_heard():
    got = run(r"""
    const srv = fakeServer(), a = await started(srv), id = a.engine.record.board, b = await joiner(srv, id);
    await b.tick();
    const mark = (dv) => { const s = dv.find('k1'); s.status = 'working'; s.work = { request: 'r-' + dv.name, kind: 'acct', who: WHO, dev: dv.engine.record.dev, mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [] }; return s; };
    const sa = mark(a), sb = mark(b);
    out.claims = [await a.engine.claim([sa]), await b.engine.claim([sb])];
    out.b = [sb.work.dev === a.engine.record.dev, sb.work.request, b.toasts];
    // A puts a sound in the trash; B, which was making it, hears that
    b.find('k2').status = 'working'; b.find('k2').work = { request: 'r9', kind: 'acct', who: WHO, dev: b.engine.record.dev, mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [{ id: 'j9', k: 1 }] };
    await b.save(); await b.tick(); await a.tick();
    const t = a.find('k2'); a.m.assets.splice(a.m.assets.indexOf(t), 1); t.trashedAt = clock.t; a.m.trash.push(t); await a.save(); await a.tick();
    await b.tick();
    out.trash = [b.trashed, b.m.trash.map((x) => x.key)];
    """)
    assert got["claims"] == [True, False]
    assert got["b"] == [True, "r-A", ["genTaken:Door"]]
    assert got["trash"] == [["k2"], ["k2"]]


def test_three_thousand_random_steps_with_lost_requests_lost_answers_and_restarts_end_the_same_everywhere():
    got = run(r"""
    let seed = 20261111;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    const pick = (list) => list[Math.floor(rnd() * list.length)];
    const srv = fakeServer(), first = await started(srv), id = first.engine.record.board;
    const devs = [first, await joiner(srv, id)];
    await devs[1].tick();
    let made = 0;
    const counts = { edit: 0, tick: 0, restart: 0, crash: 0, faults: 0 };
    function edit(dv) {
      const m = dv.m, r = rnd(), live = m.assets;
      if (r < 0.2 && live.length) pick(live).name = 'n' + Math.floor(rnd() * 1000);
      else if (r < 0.3 && live.length) { const a = pick(live); a.loop = !a.loop; }
      else if (r < 0.4) m.assets.push(sound(dv.name + 'x' + (++made), { name: 'new ' + made }));
      else if (r < 0.5 && live.length) { const a = pick(live); m.assets.splice(m.assets.indexOf(a), 1); a.trashedAt = clock.t; m.trash.push(a); }
      else if (r < 0.55 && m.trash.length) { const a = pick(m.trash); m.trash.splice(m.trash.indexOf(a), 1); delete a.trashedAt; m.assets.push(a); }
      else if (r < 0.6 && m.trash.length) { const a = pick(m.trash); dv.engine.purge([a.key]); m.trash.splice(m.trash.indexOf(a), 1); }
      else if (r < 0.67) m.cats.push({ id: 'c' + Math.floor(rnd() * 6), name: 'C', kind: 'sfx', hue: '#' + Math.floor(rnd() * 9) });
      else if (r < 0.72 && m.cats.length > 1) { const c = pick(m.cats.slice(1)); m.cats.splice(m.cats.indexOf(c), 1); }
      else if (r < 0.8 && m.cats.length) pick(m.cats).name = 'cat ' + Math.floor(rnd() * 100);
      else if (r < 0.88) m.vals.game = 'g' + Math.floor(rnd() * 100);
      else if (live.length) pick(live).chat.push({ me: true, text: dv.name + rnd().toString(36).slice(2, 5) });
      // a group id may be taken twice on one computer: keep ids unique there, as the page does
      const seen = new Set(); m.cats = m.cats.filter((c) => (seen.has(c.id) ? false : seen.add(c.id)));
    }
    for (let step = 0; step < 3000; step++) {
      const i = rnd() < 0.5 ? 0 : 1, dv = devs[i], r = rnd();
      clock.t += 1000; srv.t += 1;
      if (r < 0.45) { edit(dv); counts.edit++; await dv.save(); }
      else if (r < 0.88) {
        srv.fault = (c) => { const x = rnd(); if (x < 0.08) { counts.faults++; return 'request'; } if (x < 0.16) { counts.faults++; return 'response'; } return null; };
        await dv.tick(); srv.fault = null; counts.tick++;
      } else if (r < 0.95) { dv.engine.stop(); devs[i] = await reopen(srv, dv); counts.restart++; }
      else {
        // a round that ends with the computer gone before (or while) its last write lands
        dv.fake.fail.commit = (ops) => (rnd() < 0.5 ? new Error('gone') : null);
        await dv.tick(); dv.fake.fail = {}; dv.engine.stop(); devs[i] = await reopen(srv, dv); counts.crash++;
      }
    }
    out.counts = counts;
    out.converged = await converge(srv, devs, 30);
    const head = srv.board(id).head;
    for (const dv of devs) await dv.tick();
    out.end = [same(srv, id, ...devs), devs.map((dv) => dv.engine.status().changes), srv.board(id).head === head, Object.keys(srv.records(id)).length];
    // every sound id is unique on the board, on both computers
    out.ids = devs.map((dv) => new Set(dv.m.assets.map((a) => a.id)).size === dv.m.assets.length);
    """, timeout=600)
    c = got["counts"]
    assert c["tick"] > 1000 and c["restart"] > 100 and c["crash"] > 50 and c["faults"] > 100, c
    assert got["converged"], got
    assert got["end"][0] and got["end"][1] == [0, 0] and got["end"][2], got["end"]
    assert got["ids"] == [True, True]


def test_two_computers_through_the_scenes_of_the_contract():
    """docs/ASSET_SYNC_SPEC.md K, scenes the libraries alone can play (the page's own parts are package U's and X's).
    Every scene ends with both computers and the server holding the same records, nothing left to send, and a server
    head that another round does not move."""
    got = run(r"""
    const scenes = {};
    // Plays one scene on a fresh server and checks how it ends. fn returns what the scene itself is checked by.
    async function scene(n, fn) {
      const srv = fakeServer(), ctx = { srv, devs: [] };
      const what = await fn(ctx);
      const id = ctx.board || (ctx.devs[0] && ctx.devs[0].engine.record.board);
      const ok = await converge(srv, ctx.devs);
      const head = srv.board(id).head;
      for (const dv of ctx.devs) await dv.tick();
      scenes[n] = { what, end: [ok, same(srv, id, ...ctx.devs), ctx.devs.map((dv) => dv.engine.status().changes).every((x) => x === 0), srv.board(id).head === head] };
    }
    const pair = async (ctx) => { const a = await started(ctx.srv); const b = await joiner(ctx.srv, a.engine.record.board); await b.tick(); ctx.devs.push(a, b); return [a, b]; };
    const rec = (ctx, key) => JSON.parse(ctx.srv.records(ctx.devs[0].engine.record.board)[key] || 'null');

    // 1. A puts a real board up and B (an empty page bound to it) joins; joining writes nothing
    await scene(1, async (ctx) => {
      const a = await started(ctx.srv), id = a.engine.record.board, head = ctx.srv.board(id).head;
      const b = await joiner(ctx.srv, id); b.m.vals.demo = true; b.m.assets.push(sound('s_x', { sample: true }));
      await b.tick();
      ctx.devs.push(a, b);
      return [ctx.srv.board(id).head === head, b.m.assets.map((x) => x.key)];
    });
    // 2. two new computers make the account's first board at the same time: one board
    await scene(2, async (ctx) => {
      const a = await device(ctx.srv, 'A'), b = await device(ctx.srv, 'B');
      a.m.assets.push(sound('ka')); b.m.assets.push(sound('kb'));
      await a.save(); await b.save();
      await Promise.all([a.tick(), b.tick()]);
      ctx.devs.push(a);
      return [ctx.srv.boards.size, a.moved.length + b.moved.length, b.moved[0] === a.engine.record.board || a.moved[0] === b.engine.record.board];
    });
    // 3. different fields at once: both stay
    await scene(3, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.find('k1').name = 'A name'; b.find('k1').loop = true; await a.save(); await b.save();
      await a.tick(); await b.tick(); await a.tick();
      return [a.find('k1').name, a.find('k1').loop, b.find('k1').name, b.find('k1').loop, a.toasts.length + b.toasts.length];
    });
    // 4. the same field at once: the first to arrive stays and the other is told
    await scene(4, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.find('k1').name = 'first'; b.find('k1').name = 'second'; await a.save(); await b.save();
      await a.tick(); await b.tick();
      return [b.find('k1').name, b.toasts, a.toasts];
    });
    // 5. an answer thrown away, then the same field edited again
    await scene(5, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.find('k1').name = 'one'; await a.save();
      ctx.srv.fault = (c) => (c.dev === 'A' && c.ops ? 'response' : null); await a.tick(); ctx.srv.fault = null;
      a.find('k1').name = 'two'; await a.save(); await a.tick(); await b.tick();
      return [b.find('k1').name, a.toasts];
    });
    // 6. both make a new sound with the same name: two sounds, two ids, the same on both
    await scene(6, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.m.assets.push(sound('kA', { id: 'sfx_door', name: 'door' })); b.m.assets.push(sound('kB', { id: 'sfx_door', name: 'door' }));
      await a.save(); await b.save(); await a.tick(); await b.tick(); await a.tick(); await b.tick();
      return [a.m.assets.filter((x) => x.name === 'door').map((x) => x.key + '=' + x.id).sort(), b.m.assets.filter((x) => x.name === 'door').map((x) => x.key + '=' + x.id).sort()];
    });
    // 7. A changes a group's id (new group, sounds moved, old one deleted) while B moves a sound into the old group
    await scene(7, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.m.cats.push({ id: 'sfx2', name: 'SFX', kind: 'sfx', hue: '#1' }); for (const s of a.m.assets) s.cat = 'sfx2'; a.m.cats.splice(0, 1);
      b.m.assets.push(sound('k3', { cat: 'ui' }));
      await a.save(); await b.save(); await a.tick(); await b.tick(); await a.tick();
      return [b.m.cats.map((c) => c.id), b.m.assets.map((s) => s.cat)];
    });
    // 8. a brought-in sound's bytes go before its record with the same sha; a 3 MB one cut at its second piece goes on
    await scene(8, async (ctx) => {
      const [a, b] = await pair(ctx);
      const s = a.bring('k3', 3000000, 8); await a.save();
      let n = 0; ctx.srv.fault = (c) => (c.path.includes('/blobs/') && ++n === 2 ? 'request' : null);
      await a.tick(); ctx.srv.fault = null;
      const early = !!rec(ctx, 'asset/k3');
      await a.tick(); await b.tick();
      const heard = await b.store.bytes('ver:vk3');
      const chunks = ctx.srv.calls.filter((c) => c.path.includes('?at=')).map((c) => c.path.split('?')[1]);
      return [early, sha(heard) === s.versions[0].sha256, chunks];
    });
    // 9. the trash against an edit, and a delete for good against a restore
    await scene(9, async (ctx) => {
      const [a, b] = await pair(ctx);
      const t = a.find('k1'); a.m.assets.splice(a.m.assets.indexOf(t), 1); t.trashedAt = clock.t; a.m.trash.push(t);
      b.find('k1').description = 'edited'; await a.save(); await b.save(); await a.tick(); await b.tick(); await a.tick();
      const both = [b.m.trash.map((x) => x.key), b.find('k1').description, a.find('k1').description];
      // A deletes it for good while B takes it back out of the trash first: the delete is refused and it stays
      const r = b.find('k1'); b.m.trash.splice(b.m.trash.indexOf(r), 1); delete r.trashedAt; b.m.assets.push(r); await b.save(); await b.tick();
      a.engine.purge(['k1']); a.m.trash.splice(a.m.trash.findIndex((x) => x.key === 'k1'), 1); await a.save(); await a.tick();
      return [both, a.m.assets.map((x) => x.key).includes('k1'), b.m.assets.map((x) => x.key).includes('k1')];
    });
    // 10. one adopts the drafts, the other throws them away
    await scene(10, async (ctx) => {
      const [a, b] = await pair(ctx);
      const d1 = version('d1', bytesOf(20, 1)), d2 = version('d2', bytesOf(20, 2));
      const s = a.find('k1'); a.store.hold(d1.key, new Blob([bytesOf(20, 1)])); a.store.hold(d2.key, new Blob([bytesOf(20, 2)]));
      s.status = 'review'; s.drafts.push(d1, d2); s.pick = 0; s.work = { request: 'r', kind: 'acct', who: WHO, dev: a.engine.record.dev, mode: 'make', text: '', n: 2, at: 1, before: 'pending', jobs: [] };
      await a.save(); await a.tick(); await b.tick();
      const sa = a.find('k1'), sb = b.find('k1');
      sa.versions.push(...sa.drafts.splice(0)); sa.current = 1; sa.status = 'draft'; delete sa.work;
      sb.drafts.splice(0); sb.status = 'pending'; delete sb.work;
      await a.save(); await b.save(); await a.tick(); await b.tick(); await a.tick();
      return [b.find('k1').versions.map((v) => v.id), b.find('k1').drafts.length, b.find('k1').status];
    });
    // 11. both ask for the same tile: one claim wins, the other sends nothing and hears that it is taken
    await scene(11, async (ctx) => {
      const [a, b] = await pair(ctx);
      const mark = (dv) => { const s = dv.find('k1'); s.status = 'working'; s.work = { request: 'r' + dv.name, kind: 'acct', who: WHO, dev: dv.engine.record.dev, mode: 'make', text: '', n: 1, at: 1, before: 'pending', jobs: [] }; return s; };
      const claims = await Promise.all([a.engine.claim([mark(a)]), b.engine.claim([mark(b)])]);
      return [claims, b.toasts.concat(a.toasts)];
    });
    // 13. the API restarts in the middle of an upload: it goes on from what the server has
    await scene(13, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.bring('k3', 2500000, 13); await a.save();
      let n = 0; ctx.srv.fault = (c) => (c.path.includes('/blobs/') && ++n >= 2 ? 'request' : null);
      await a.tick();
      ctx.srv.fault = null; ctx.srv.up = 0; for (const x of ctx.srv.boards.values()) x.seen.clear(); // restarted: parts on disk stay
      await a.tick(); await b.tick();
      return ctx.srv.calls.filter((c) => c.path.includes('?at=')).map((c) => c.path.split('?')[1]);
    });
    // 14. one computer edits fifty times while offline, then comes back
    await scene(14, async (ctx) => {
      const [a, b] = await pair(ctx);
      ctx.srv.down = true;
      for (let i = 0; i < 50; i++) { a.find(i % 2 ? 'k1' : 'k2').name = 'off ' + i; a.m.assets.push(sound('o' + i)); await a.save(); await a.tick(); }
      b.find('k1').loop = true; await b.save();
      ctx.srv.down = false;
      await b.tick(); await a.tick(); await b.tick();
      return [b.m.assets.length, b.find('k1').name, b.find('k2').name, b.find('k1').loop, a.toasts];
    });
    // 16. "start with an empty board": a new board for this computer only, home stays; offline it does not move
    await scene(16, async (ctx) => {
      const [a, b] = await pair(ctx);
      const home = a.engine.record.board;
      ctx.srv.down = true; a.find('k1').name = 'unsent'; await a.save(); clock.t += 30000;
      const offline = await a.engine.flush(2000);
      ctx.srv.down = false;
      const online = await a.engine.flush(2000);
      const blank = await device(ctx.srv, 'A2', { seed: 'blank', make: { first: false, home: false } });
      blank.m.cats.push({ id: 'x', name: 'X', kind: 'sfx', hue: '#9' }); await blank.save(); await blank.tick();
      ctx.board = home;
      return [offline, online, ctx.srv.boards.size, ctx.srv.home === home, b.m.assets.length];
    });
    // 17. "start again from samples": nothing goes up, home stays
    await scene(17, async (ctx) => {
      const [a, b] = await pair(ctx);
      const home = ctx.srv.home, before = ctx.srv.calls.length;
      const s = await device(ctx.srv, 'A3', { seed: 'sample', make: { first: false, home: false } });
      s.m.vals.demo = true; s.m.assets.push(sound('s_one', { sample: true })); await s.save(); await s.tick();
      return [ctx.srv.calls.length - before, ctx.srv.home === home, ctx.srv.boards.size];
    });
    // 18. a computer with real work comes to an account that has a board: home opens, its own board goes up apart
    await scene(18, async (ctx) => {
      const [a, b] = await pair(ctx);
      const l = await device(ctx.srv, 'L'); l.m.assets.push(sound('kl')); await l.save(); await l.tick();
      l.engine.stop();
      const up = await reopen(ctx.srv, l, { upload: true }); await up.tick();
      return [l.moved[0] === a.engine.record.board, ctx.srv.boards.size, same(ctx.srv, up.engine.record.board, up)];
    });
    // 20. the server's database goes back to an older file
    await scene(20, async (ctx) => {
      const [a, b] = await pair(ctx);
      const id = a.engine.record.board, old = structuredClone([...ctx.srv.board(id).recs]), head = ctx.srv.board(id).head;
      a.find('k1').name = 'newer'; await a.save(); await a.tick(); await b.tick();
      ctx.srv.board(id).recs = new Map(old); ctx.srv.board(id).head = head; ctx.srv.epoch = 'e9';
      await a.tick(); await b.tick(); await a.tick();
      return [b.find('k1').name, a.engine.record.epoch, b.engine.record.epoch];
    });
    // 21. a client with an old protocol stops and says so
    await scene(21, async (ctx) => {
      const [a, b] = await pair(ctx);
      ctx.srv.proto = 2; b.find('k1').name = 'old client'; await b.save(); await b.tick();
      const told = [b.toasts, b.engine.state];
      ctx.srv.proto = 1; ctx.devs.pop();
      return told;
    });
    // 23. A deletes a group while B renames it, in both orders: the same on both computers
    for (const [n, aFirst] of [['23a', true], ['23b', false]]) await scene(n, async (ctx) => {
      const [a, b] = await pair(ctx);
      a.m.cats.push({ id: 'g', name: 'G', kind: 'sfx', hue: '#4' }); await a.save(); await a.tick(); await b.tick();
      const del = async () => { a.m.cats.splice(a.m.cats.findIndex((c) => c.id === 'g'), 1); await a.save(); await a.tick(); };
      const ren = async () => { b.m.cats.find((c) => c.id === 'g').name = 'Renamed'; await b.save(); await b.tick(); };
      if (aFirst) { await del(); await ren(); } else { await ren(); await del(); }
      await a.tick(); await b.tick();
      return [a.m.cats.map((c) => c.id + ':' + c.name), b.m.cats.map((c) => c.id + ':' + c.name), [...a.toasts, ...b.toasts]];
    });
    out.scenes = scenes;
    """, timeout=600)
    s = got["scenes"]
    for n, v in s.items():
        assert v["end"] == [True, True, True, True], (n, v)
    assert s["1"]["what"] == [True, ["k1", "k2"]]
    assert s["2"]["what"] == [1, 1, True]
    assert s["3"]["what"] == ["A name", True, "A name", True, 0]
    assert s["4"]["what"] == ["first", ["syncLost:second"], []]
    assert s["5"]["what"] == ["two", []]
    door = s["6"]["what"]
    assert door[0] == door[1] and len({x.split("=")[1] for x in door[0]}) == 2
    assert s["7"]["what"] == [["sfx2"], ["sfx2", "sfx2", "sfx2"]]
    early, heard, chunks = s["8"]["what"]
    assert early is False and heard and chunks == ["at=0&size=3000000", "at=1000000&size=3000000", "at=1000000&size=3000000", "at=2000000&size=3000000"]
    assert s["9"]["what"] == [[["k1"], "edited", "edited"], True, True]
    assert s["10"]["what"] == [["d1", "d2"], 0, "draft"]
    assert s["11"]["what"][0] in ([True, False], [False, True]) and s["11"]["what"][1] == ["genTaken:Door"]
    assert s["13"]["what"] == ["at=0&size=2500000", "at=1000000&size=2500000", "at=1000000&size=2500000", "at=2000000&size=2500000"]
    assert s["14"]["what"] == [52, "off 49", "off 48", True, []]
    assert s["16"]["what"] == [{"ok": False, "reason": "syncOff"}, {"ok": True, "reason": ""}, 2, True, 2]
    assert s["17"]["what"] == [0, True, 1]
    assert s["18"]["what"] == [True, 2, True]
    assert s["20"]["what"] == ["newer", "e9", "e9"]
    assert s["21"]["what"] == [["syncOld"], "old"]
    assert s["23a"]["what"][0] == s["23a"]["what"][1] and s["23b"]["what"][0] == s["23b"]["what"][1]
