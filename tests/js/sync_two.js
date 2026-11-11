// Scenes 12 and 24 of docs/ASSET_SYNC_SPEC.md K against the real API: tests/test_asset_sync_two.py starts it
// (OLMUSE_GEN_FAKE=1, OLMUSE_BOARD_SYNC=1, a temp folder, a free port) and hands in, on stdin, { base, origin, token, who }.
// Two computers A and B of one account: each its own in-memory IndexedDB, the real store.js, board.js, gen.js and
// sync.js wired the way app.js wires them, and Node's fetch. Rounds of sync are run by hand; the clock of a computer
// can be put ahead (skew) to stand for the time a stopped computer has been away.
'use strict';
globalThis.window = globalThis;
const path = require('path'), nodeCrypto = require('crypto');
const DIR = process.env.ASSET_STUDIO_DIR || path.join(__dirname, '..', '..', 'studio_frontend', 'asset_studio'); // another copy, to see the scenes fail
for (const f of ['data.js', 'synth.js', 'measure.js', 'store.js', 'board.js', 'gen.js', 'sync.js']) require(path.join(DIR, f));
const S = window.assetStore, B = window.assetBoard, G = window.assetGen, Y = window.assetSync, M = window.assetMeasure;
const sha = (u8) => nodeCrypto.createHash('sha256').update(u8).digest('hex');
const settle = async (n = 30) => { for (let i = 0; i < n; i++) await new Promise((ok) => setImmediate(ok)); };
const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));
async function until(done, ms = 30000) { for (const end = Date.now() + ms; !(await done());) { if (Date.now() > end) throw new Error('waited too long'); await wait(50); } }

// IndexedDB in memory, one database per computer; a transaction's writes land together a turn after it opened.
function fakeIdb() {
  const stores = new Map();
  const keep = (v) => (v instanceof Blob ? v : structuredClone(v));
  function transaction() {
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
      for (const o of ops) { const s = stores.get(o.store); if (o.op === 'put') s.set(o.key, o.value); else if (o.op === 'delete') s.delete(o.key); else s.clear(); }
      if (q.oncomplete) q.oncomplete({ target: q });
    });
    return q;
  }
  return { indexedDB: { open(name) {
    const r = { result: null, onsuccess: null, onerror: null, onupgradeneeded: null };
    setImmediate(() => { r.result = { name, createObjectStore: (n) => { stores.set(n, new Map()); }, transaction, close() {} }; if (!stores.size && r.onupgradeneeded) r.onupgradeneeded({ target: r }); r.onsuccess({ target: r }); });
    return r;
  } } };
}

// The page around the engine: the live board and app.js's snapshot() of it.
function model() {
  const m = { assets: [], trash: [], cats: [{ id: 'ui', name: 'UI', kind: 'sfx', hue: '#1' }], refs: [], dynamics: [],
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
    agentLog: [], trash: m.trash.map(one(true)), dynamics: m.dynamics, assets: m.assets.map(one(false)) };
}
function applyTo(m, data) {
  const open = (x) => { const { hasSource, ...a } = x; a.progress = 0; a.versions ||= []; a.drafts ||= []; return a; };
  m.assets.splice(0, m.assets.length, ...data.assets.map(open)); m.trash.splice(0, m.trash.length, ...(data.trash || []).map(open));
  m.cats.splice(0, m.cats.length, ...(data.cats || [])); m.refs.splice(0, m.refs.length, ...(data.projectRefs || [])); m.dynamics.splice(0, m.dynamics.length, ...(data.dynamics || []));
  for (const k of ['game', 'brief', 'platform', 'loud', 'demo', 'stage', 'idRule', 'exportOpts']) if (data[k] !== undefined) m.vals[k] = data[k];
}
const sound = (key, more = {}) => ({ key, id: 'sfx_' + key, name: 'Sound ' + key, cat: 'ui', music: false, loop: false, layers: [], status: 'pending', versions: [], current: 0, drafts: [], pick: -1, chat: [], progress: 0, ...more });

// One computer of the account. o.fake: its database again (a reopened page); o.still: its timers never fire (a
// computer that stopped: nothing of it runs unless the scene calls it).
async function computer(env, name, o = {}) {
  const dv = { name, fake: o.fake || fakeIdb(), m: model(), skew: 0, calls: [], toasts: [], lost: [], engine: null };
  const fetcher = async (url, init) => {
    dv.calls.push(init.method + ' ' + url.slice(env.base.length).split('?')[0]);
    return fetch(url, { ...init, headers: { ...init.headers, Origin: env.origin } });
  };
  dv.snapshot = () => snap(dv.m);
  const keys = () => { const want = new Map(); for (const a of [...dv.m.assets, ...dv.m.trash]) for (const v of [...a.versions, ...a.drafts]) for (const k of S.versionKeys(v)) want.set(k, null); return want; };
  dv.store = S.create({ indexedDB: dv.fake.indexedDB, snapshot: dv.snapshot, keys, assets: () => dv.m.assets, apply: (data, buffers, info) => { applyTo(dv.m, data); dv.info = info; },
    extra: () => (dv.engine ? dv.engine.extra() : {}), remote: B.remoteKeys, fetch: (k) => dv.engine.fetch(k), pending: () => !!dv.engine && dv.engine.pending });
  await dv.store.lock();
  dv.result = await dv.store.restore();
  const record = (dv.info && dv.info.sync) || Y.record({ who: env.who, board: o.board || Y.newBoard(), made: !!o.made, make: o.make || { first: true, home: true } });
  const timers = o.still ? { setTimeout: () => 0, clearTimeout: () => {} } : {};
  let ready = null;
  const engineP = new Promise((ok) => { ready = ok; });
  dv.gen = G.create({
    store: dv.store, assets: () => dv.m.assets, fetch: fetcher, now: () => performance.now(), wall: () => Date.now(), ...timers,
    uuid: () => nodeCrypto.randomUUID(), sha256: async (u8) => sha(u8), measure: M, peaks: S.peaksOf,
    project: () => ({ game: 'Moon', style: '', platform: 'mobile', loud: [-20, -14] }),
    item: (a) => ({ kind: a.music ? 'music' : 'sfx', loop: !!a.loop, id: a.id, name: a.name, description: a.description || '' }),
    lang: () => 'en', text: (key, n) => (n === undefined ? key : key + ':' + n), toast: (t) => dv.toasts.push(t), toastBusy: () => false, post: () => {}, hidden: () => false,
    render: () => {}, done: () => {}, onQuote: () => {},
    dev: () => record.dev, ready: () => engineP.then((e) => e.ready()), claim: (list) => engineP.then((e) => e.claim(list)),
    handover: { info: () => dv.engine.peers(), take: (list) => dv.engine.push(list) },
  });
  dv.engine = Y.create({ store: dv.store, call: dv.gen.call, identity: () => dv.gen.identity, sync: record, snapshot: dv.snapshot, model: () => dv.m,
    quiet: () => true, redraw: () => {}, lost: (x) => dv.lost.push(x.what), onTrash: (list) => dv.gen.cancel(list), moved: () => {}, hidden: () => false,
    sha256: async (u8) => sha(u8), now: () => Date.now() + dv.skew, setTimeout: () => 0, clearTimeout: () => {} });
  ready(dv.engine);
  if (!(await dv.gen.token({ token: env.token, ttl: 900, api: env.base }))) throw new Error(name + ': the token was not taken');
  dv.gen.attach(); // what app.js does after the restore and with every token
  await settle();
  dv.tick = async () => { await dv.engine.tick(); await settle(); };
  dv.records = () => Object.fromEntries([...B.toRecords(dv.snapshot())].map(([k, d]) => [k, B.canon(d)]));
  dv.find = (key) => dv.m.assets.find((a) => a.key === key);
  return dv;
}
const sorted = (o) => JSON.stringify(Object.entries(o).sort(([p], [q]) => (p < q ? -1 : p > q ? 1 : 0)));
async function converge(dvs, rounds = 12) {
  for (let i = 0; i < rounds; i++) {
    for (const dv of dvs) await dv.tick();
    if (dvs.every((dv) => dv.engine.status().changes === 0)) { for (const dv of dvs) await dv.tick(); return true; }
    await wait(1100); // requests of one engine are at least a second apart
  }
  return false;
}
const ENDED = ['done', 'failed', 'cancelled', 'refunded', 'expired'];
async function jobsEnded(dv, ids) {
  const r = await dv.gen.call('POST', '/jobs/status', JSON.stringify({ ids }));
  return r.status === 200 && r.data.jobs.length === ids.length && r.data.jobs.every((j) => ENDED.includes(j.status));
}
// What the server holds of the board, read the way a third computer would: every record from rev 0.
async function serverRecords(dv) {
  const id = dv.engine.record.board, out = {};
  let since = 0, more = true, head = 0;
  while (more) {
    const r = await dv.gen.call('POST', `/boards/${id}/sync`, JSON.stringify({ v: 1, dev: Y.newDev(), since, ops: [] }));
    if (r.status !== 200) throw new Error('server read ' + r.status + ' ' + r.code);
    for (const c of r.data.changes) { if (c.gone) delete out[c.kind + '/' + c.uid]; else out[c.kind + '/' + c.uid] = B.canon(c.data); }
    since = r.data.next; more = r.data.more; head = r.data.head;
  }
  return { records: out, head };
}

(async () => {
  const env = JSON.parse(require('fs').readFileSync(0, 'utf8'));
  const out = {};
  // The board goes up from A with one sound; B joins it.
  const a = await computer(env, 'A', { still: true });
  a.m.assets.push(sound('k1', { name: 'Door' }));
  await a.store.save(); await a.tick();
  const board = a.engine.record.board;
  const b = await computer(env, 'B', { board, made: true, make: { first: false, home: false } });
  await b.tick();
  out.joined = [!!b.find('k1'), a.engine.record.made];

  // Scene 12. A asks for the sound and stops before the drafts come back (its timers never fire: no poll).
  const asked = await a.gen.generate([a.find('k1')], { drafts: 1 });
  out.asked = [asked.ok, asked.reason || ''];
  await until(() => !!(a.find('k1').work && a.find('k1').work.jobs.length && a.find('k1').work.jobs.every((j) => j.id)));
  const ids = a.find('k1').work.jobs.map((j) => j.id);
  out.jobRecordOnServer = (await serverRecords(b)).records['asset/k1'].includes(a.engine.record.dev);
  await converge([a, b]);
  out.bSeesAsWork = !!(b.find('k1').work && b.find('k1').work.dev === a.engine.record.dev);
  await until(() => jobsEnded(b, ids));
  // A is still there (it has just been seen): B takes nothing over, however long the API has been up.
  await wait(1100); await a.tick(); await wait(1100); await b.tick();
  out.whileOnline = (await b.gen.handover()).length;
  out.whileOnlineDev = b.find('k1').work.dev === a.engine.record.dev;
  // B's clock runs 200 s past A's last round: A counts as gone and B takes the work over on the server.
  b.skew = 200000;
  const won = await b.gen.handover();
  out.taken = won.map((x) => x.key);
  out.serverHasB = (await serverRecords(b)).records['asset/k1'].includes(b.engine.record.dev);
  // B collects the drafts A asked for.
  await until(() => { const x = b.find('k1'); return !x.work && x.drafts.length + x.versions.length > 0; }, 30000).catch(() => {});
  out.bGotDrafts = [b.find('k1').status, b.find('k1').drafts.length + b.find('k1').versions.length, !!b.find('k1').work, b.toasts];
  b.skew = 0;
  await converge([b]); // A is still away

  // Scene 24. A opens again from what its database holds (its record still says the work is A's).
  const before = a.calls.length;
  const a2 = await computer(env, 'A', { fake: a.fake });
  out.reopenedHeldMine = !!(a2.find('k1').work && a2.find('k1').work.dev === a2.engine.record.dev);
  out.converged = await converge([a2, b]);
  await wait(2500); // a poll or a cancel of A would have gone out by now
  await settle();
  const aCalls = [...a.calls.slice(before), ...a2.calls];
  out.aCalls = aCalls;
  out.aCancelOrPoll = aCalls.filter((c) => / \/jobs/.test(c)); // no poll, collect, cancel or new request of A
  out.aEnd = { status: a2.find('k1').status, sounds: a2.find('k1').drafts.length + a2.find('k1').versions.length, work: !!a2.find('k1').work };
  out.bEnd = { status: b.find('k1').status, sounds: b.find('k1').drafts.length + b.find('k1').versions.length };
  const srv = await serverRecords(b);
  out.same = sorted(a2.records()) === sorted(srv.records) && sorted(b.records()) === sorted(srv.records);
  out.left = [a2.engine.status().changes, b.engine.status().changes];
  const head = srv.head;
  await converge([a2, b]);
  out.headStill = (await serverRecords(b)).head === head;
  a2.engine.stop(); b.engine.stop();
  console.log(JSON.stringify(out));
  process.exit(0);
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
