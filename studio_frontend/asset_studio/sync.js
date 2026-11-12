// Keeps one board in step between the computers of an account (docs/ASSET_SYNC_SPEC.md, E and F): it receives what
// changed on the server, merges it into the live board (board.js), sends what changed here as conditional writes of
// single records, and moves the sound bytes those records point at. The network (gen.call), the store, the clock and
// the timers are handed in, so Node runs this file in tests.
//
// assetSync.create(deps) -> one board's engine. deps:
//   store (assetStore made with extra: () => engine.extra(), remote: assetBoard.remoteKeys, fetch: (k) => engine.fetch(k),
//   pending: () => engine.pending), call (gen.call), identity() -> { kind, who } of the token in hand, sync (the record
//   read with the board: info.sync), snapshot() (the page's), model() (board.js's model), quiet() -> the page may be
//   drawn again now (no text field held, no IME, no pointer down, no tile menu), redraw(list), lost({ what, name, key })
//   for the toasts syncLost, syncGone, syncOff, syncFull, syncOld, genTaken, boardLimit, onTrash(assets) (sounds another
//   computer put in the trash: the page cancels their work here), moved({ board }) (POST /boards named another board),
//   hidden(), sha256(bytes) -> hex, now() (ms), setTimeout, clearTimeout. upload: true makes an engine that only sends
//   (a board kept apart from the account's, E5): it receives nothing and patches nothing.
// The engine: start(), stop(), tick() (one round, for tests and for start), nudge() (something changed here),
//   extra() -> { sync } (written with the board record), pending (the board was never received yet), ready() (resolves
//   once this visit's first receiving is over, or the engine will not run), claim(assets) -> true (H), push(assets) ->
//   the assets whose records the server took, purge(keys) (sounds deleted for good), fetch(key) -> bytes | null,
//   status() -> { state, changes, sounds: [sent, all], blocked }, flush(ms) -> { ok, reason }, peers() (for
//   gen.handover), done() (an upload engine: resolves when all of it is on the server), record (the sync record).
// Also: record(...) a new sync record, dbName, newBoard, newDev, scan(indexedDB, who), list(call),
// open(call, board), pointer helpers.
(function (factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  const root = typeof window !== 'undefined' ? window : typeof self !== 'undefined' ? self : null;
  if (root) root.assetSync = api;
})(function () {
  'use strict';

  const root = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : {};
  const B = () => root.assetBoard || (typeof require === 'function' ? require('./board.js') : null);
  const PROTO = 1, OPS_MAX = 400, REQ_BYTES = 1200000, CHUNK_MAX = 1000000, BLOB_MAX = 60 * 1024 * 1024, SHAS_MAX = 200;
  const PREFETCH_MAX = 4 * 1024 * 1024, PREFETCH_AT_ONCE = 2, HEAL_MS = 30 * 60000;
  // How often a round runs: 2 s while something changed in the last 30 s, else 5 s, 15 s in a hidden tab. A change
  // here is gathered for 0.8 s and requests are at least 1 s apart. Failures wait 2, 4, 8 ... 30 s.
  const FAST = 2000, SLOW = 5000, HIDDEN = 15000, ACTIVE = 30000, GATHER = 800, GAP = 1000, BACK_MIN = 2000, BACK_MAX = 30000;
  const OFF_AFTER = 20000, LOST_EVERY = 4000, REDRAW_MS = 500, DB = 'olmuse-asset-board';
  const ORDER = { meta: 0, cat: 1, asset: 2, ref: 3, dyn: 3 };

  /* ---------- names and new records ---------- */
  const hex = (n, random = Math.random) => Array.from({ length: n }, () => Math.floor(random() * 16).toString(16)).join('');
  const newBoard = (random) => hex(32, random), newDev = (random) => hex(16, random);
  const dbName = (who, board) => `${DB}.${who}.${String(board).slice(0, 12)}`;
  // make: what the first POST /boards says ({ first, home }), purge: sounds deleted for good still to be sent.
  function record(o) {
    const x = o || {};
    return { v: 1, who: x.who, board: x.board, made: !!x.made, make: { first: !!(x.make && x.make.first), home: !!(x.make && x.make.home) }, epoch: x.epoch ?? null, cursor: 0,
      dev: x.dev || newDev(x.random), pulled: !!x.pulled, seed: x.seed ?? null, shadow: {}, purge: [], at: x.at ?? 0 };
  }
  // localStorage 'asset-sync': { v: 1, anon, accts: { who16: { db } } }, the pointer to the database to open.
  const pointer = {
    read(ls) { try { const x = JSON.parse(ls.getItem('asset-sync')); return x && x.v === 1 && typeof x === 'object' ? x : null; } catch { return null; } },
    write(ls, x) { try { ls.setItem('asset-sync', JSON.stringify({ v: 1, anon: x.anon ?? null, accts: x.accts || {} })); return true; } catch { return false; } },
  };
  // Every account database of who in this browser (the default one too: the first computer's board stays there), newest sync first: [{ name, sync }]. null where the browser cannot
  // list its databases (the page then asks the server for home).
  async function scan(indexedDB, who) {
    if (!indexedDB || typeof indexedDB.databases !== 'function') return null;
    let all = [];
    try { all = await indexedDB.databases(); } catch { return null; }
    const out = [];
    for (const { name } of all || []) {
      if (typeof name !== 'string' || (name !== DB && !name.startsWith(DB + '.'))) continue;
      const sync = await new Promise((ok) => {
        let r;
        try { r = indexedDB.open(name); } catch { ok(null); return; }
        r.onupgradeneeded = () => { try { r.transaction.abort(); } catch { /* nothing there */ } };
        r.onerror = () => ok(null); r.onblocked = () => ok(null);
        r.onsuccess = () => {
          const db = r.result;
          try {
            const q = db.transaction('board').objectStore('board').get('sync');
            q.onsuccess = () => { ok(q.result || null); if (db.close) db.close(); };
            q.onerror = () => { ok(null); if (db.close) db.close(); };
          } catch { ok(null); }
        };
      });
      if (sync && sync.who === who) out.push({ name, sync });
    }
    return out.sort((p, q) => (q.sync.at || 0) - (p.sync.at || 0));
  }
  const list = (call) => call('GET', '/boards');
  const open = (call, board) => call('POST', `/boards/${board}/open`, JSON.stringify({ v: PROTO }));

  function create(deps) {
    const d = deps || {}, board = B(), store = d.store, call = d.call;
    const now = d.now || (() => Date.now());
    const later = d.setTimeout || ((fn, ms) => setTimeout(fn, ms)), unlater = d.clearTimeout || ((t) => clearTimeout(t));
    const upload = !!d.upload;
    const S = d.sync && typeof d.sync === 'object' ? d.sync : null;
    if (S) { S.shadow ||= {}; S.purge ||= []; S.make ||= { first: false, home: false }; S.cursor ||= 0; }
    const say = (what, name, key) => { if (d.lost) d.lost({ what, name, key }); };
    const model = () => d.model();

    // has: shas this board's server is known to hold. parts: where an upload left off. blocked: key -> the text the
    // server refused for good (sent again only once it changes). last: each record's text in the previous round.
    const has = new Set(), parts = new Map(), blocked = new Map(), silent = new Set();
    let last = new Map(), purge = new Set(S ? S.purge : []);
    for (const [key, sh] of S ? Object.entries(S.shadow) : []) if (sh && !sh.gone && typeof sh.json === 'string') for (const x of shasOf(key, sh.json)) has.add(x);
    // lane: one request at a time. state: the engine's own; off (sync_off, acct_only, no_board), old (upgrade),
    // stopped (stop()). resetting: the server came back from a backup and everything is received again (mine wins).
    let lane = Promise.resolve(), timer = 0, timerAt = 0, started = false, stopped = false, off = false, old = false, resetting = false;
    let lastReq = -Infinity, activity = -Infinity, failSince = 0, toldOff = false, backoff = 0, rest = 0, lastLost = -Infinity, toldFull = false;
    let hasBoard = store && store.restored === 'restored', healAt = now() + HEAL_MS, touched = true, firstPull = !S || !S.pulled;
    // A database that was opened empty to receive a board that is already on the server: once received, what the page
    // started with and the server does not have (an empty board) is not this board's.
    const fresh = !!S && !S.pulled && !!S.made && !S.seed && store && store.restored === 'empty';
    let server = { up: 0, now: 0, at: 0, peers: [] }, sending = { sent: 0, all: 0 };
    const draw = new Set();
    let drawTimer = 0;
    let readyOk = null;
    const readyP = new Promise((ok) => { readyOk = ok; });
    let doneOk = null;
    const doneP = new Promise((ok) => { doneOk = ok; });
    const settleReady = () => { if (readyOk) { readyOk(); readyOk = null; } };

    function shasOf(key, json) {
      const kind = key.slice(0, key.indexOf('/'));
      try { return board.shasOf(kind, JSON.parse(json)).map((x) => x.sha).filter(Boolean); } catch { return []; }
    }
    const split = (key) => { const i = key.indexOf('/'); return [key.slice(0, i), key.slice(i + 1)]; };
    const parse = (sh) => (sh && !sh.gone && typeof sh.json === 'string' ? JSON.parse(sh.json) : null);
    const nameOf = (data) => (data && data.name !== undefined ? data.name : data && data.game !== undefined ? data.game : null);
    const exclusive = (fn) => { const p = lane.then(fn); lane = p.catch(() => {}); return p; };
    const records = () => board.toRecords(d.snapshot());

    /* ---------- may this run at all ---------- */
    function eligible() {
      if (!S || stopped || off || old) return false;
      const id = d.identity ? d.identity() : null;
      if (!id || id.kind !== 'acct' || id.who !== S.who) return false;
      return !!store && store.locked && store.ready && !store.paused && store.restored !== 'failed';
    }
    function quit(how) {
      if (how === 'old') { old = true; say('syncOld'); } else off = true;
      unlater(timer); timer = 0;
      settleReady();
    }

    /* ---------- one request, and what a failed one does ---------- */
    async function post(path, body, opts) {
      lastReq = now();
      const r = await call(opts && opts.method ? opts.method : 'POST', path, body === undefined ? undefined : opts && opts.raw ? body : JSON.stringify(body), opts);
      if (r.status === 200) { failSince = 0; toldOff = false; backoff = 0; return r; }
      if (r.status === 403 && (r.code === 'sync_off' || r.code === 'acct_only')) quit('off');
      else if (r.status === 409 && r.code === 'upgrade') quit('old');
      else if (r.status === 404 && r.code === 'no_board') quit('off');
      else if (r.status === 429 || (r.status === 503 && r.retry)) rest = now() + Math.max(1, r.retry || 1) * 1000;
      else if (r.status === 0 || r.status >= 500) {
        backoff = Math.min(BACK_MAX, backoff ? backoff * 2 : BACK_MIN);
        if (!failSince) failSince = now();
        if (!toldOff && now() - failSince >= OFF_AFTER) { toldOff = true; say('syncOff'); }
      }
      return r;
    }
    const save = () => { S.at = now(); S.purge = [...purge]; return store.saveBoard({ sync: true }); };

    /* ---------- receiving ---------- */
    function lostOnce(what, name, key) { if (now() - lastLost < LOST_EVERY) return; lastLost = now(); say(what, name, key); }
    // One record that changed on the server, merged into the board. cur: the records of the board now (kept current).
    function receive(c, cur) {
      const key = c.kind + '/' + c.uid, sh = S.shadow[key];
      if (sh && sh.rev >= c.rev) return;
      const theirs = c.gone ? null : c.data, mine = cur.has(key) ? cur.get(key) : null, own = c.dev === S.dev;
      if (!upload) {
        const m = board.merge3(c.kind, parse(sh), mine, theirs, own || resetting);
        if (board.canon(m.data) !== board.canon(mine)) {
          const was = c.kind === 'asset' ? findAsset(c.uid) : null, wasTrashed = !!(mine && mine.trashedAt);
          const obj = board.patch(model(), c.kind, c.uid, m.data);
          if (m.data) cur.set(key, m.data); else cur.delete(key);
          if (m.data) purge.delete(key);
          if (!own) {
            draw.add(obj || was || c.kind);
            if (c.kind === 'asset' && m.data && m.data.trashedAt && !wasTrashed && obj && d.onTrash) d.onTrash([obj]);
            if (c.kind === 'asset' && m.data) prefetch(m.data);
          }
        }
        if (!own) {
          activity = now();
          if (m.lost) lostOnce('syncLost', nameOf(mine) ?? nameOf(theirs), key);
          if (m.gone) say('syncGone', nameOf(mine), key);
        }
      }
      S.shadow[key] = { rev: c.rev, born: c.born || (sh && sh.born) || c.rev, dev: c.dev, at: c.at, gone: !!c.gone, json: c.data != null ? board.canon(c.data) : sh ? sh.json : null };
      if (!c.gone) for (const x of shasOf(key, S.shadow[key].json)) has.add(x);
      touched = true;
    }
    // What every sync answer brings: the server's clock and peers, the changes, the cursor. Repairs run only once
    // nothing more is waiting. Returns 'reset' when the server came back from a backup (everything again from 0).
    async function take(data, cur) {
      server = { up: +data.up || 0, now: +data.now || 0, at: now(), peers: Array.isArray(data.peers) ? data.peers : [] };
      if ((S.epoch != null && data.epoch != null && data.epoch !== S.epoch) || (typeof data.head === 'number' && data.head < S.cursor)) {
        S.shadow = {}; S.cursor = 0; S.epoch = data.epoch; has.clear(); parts.clear(); resetting = true;
        await save();
        return 'reset';
      }
      if (data.epoch != null) S.epoch = data.epoch;
      for (const c of Array.isArray(data.changes) ? data.changes : []) if (c && typeof c.kind === 'string') receive(c, cur);
      if (typeof data.next === 'number') S.cursor = Math.max(S.cursor, data.next);
      if (!data.more && !upload) {
        if (fresh && !S.pulled) forget(cur);
        if (touched) repair();
        if (!S.pulled) S.pulled = true;
        resetting = false;
      }
      await save();
      if (!data.more) settleReady();
      flushDraw();
      return data.more ? 'more' : 'done';
    }
    // The first receiving into an empty database: records the server does not have are dropped from the page.
    function forget(cur) {
      for (const key of [...cur.keys()]) {
        if (S.shadow[key] && !S.shadow[key].gone) continue;
        const [kind, uid] = split(key);
        if (kind === 'meta') continue;
        board.patch(model(), kind, uid, null); cur.delete(key);
      }
    }
    // After a receiving with nothing more to come: shown ids made unique, sounds in a group that is gone moved to one
    // that is there, status made to agree with the lists. What changes goes up as an ordinary change next round.
    function repair() {
      touched = false;
      const m = model(), changed = new Set(board.fixIds(m, S.shadow));
      if (m.fitCat) for (const a of [...m.assets, ...m.trash]) if (!m.cats.some((c) => c.id === a.cat)) { a.cat = m.fitCat(a.cat); changed.add(a); }
      for (const [key, data] of records()) {
        if (!key.startsWith('asset/')) continue;
        const fixed = board.sane(board.copy(data));
        if (board.canon(fixed) !== board.canon(data)) { const obj = board.patch(m, 'asset', key.slice(6), fixed); if (obj) changed.add(obj); }
      }
      // The first receiving lists the sounds in the order they were made on the server.
      if (firstPull) {
        firstPull = false;
        const bornOf = (a) => { const s = S.shadow['asset/' + a.key]; return s && s.born ? s.born : Infinity; };
        const sorted = m.assets.map((a, i) => [a, i]).sort((p, q) => (bornOf(p[0]) - bornOf(q[0])) || p[1] - q[1]).map((x) => x[0]);
        if (sorted.some((a, i) => a !== m.assets[i])) { m.assets.splice(0, m.assets.length, ...sorted); changed.add('order'); }
      }
      for (const x of changed) draw.add(x);
    }
    function flushDraw() {
      if (!draw.size || drawTimer) return;
      if (d.quiet && !d.quiet()) { drawTimer = later(() => { drawTimer = 0; flushDraw(); }, REDRAW_MS); return; }
      const list = [...draw];
      draw.clear();
      if (d.redraw) d.redraw(list);
    }
    async function pull() {
      for (let n = 0; n < 100000; n++) {
        const r = await post(`/boards/${S.board}/sync`, { v: PROTO, dev: S.dev, since: S.cursor, ops: [] });
        if (r.status !== 200 || !r.data) return false;
        const how = await take(r.data, records());
        if (how === 'done') return true;
      }
      return false;
    }

    /* ---------- what to send ---------- */
    const findAsset = (uid) => { const m = model(); return m.assets.find((a) => a.key === uid) || m.trash.find((a) => a.key === uid) || null; };
    // The records that differ from what the server was last known to hold. A sound that is gone from the page without
    // being deleted for good comes back in the trash. While the page is busy (a field held) only records that held
    // still since the last round go. only: a set of keys to look at (a claim).
    function dirty(only) {
      let cur = records();
      let back = false;
      for (const [key, sh] of Object.entries(S.shadow)) {
        if (!sh || sh.gone || cur.has(key) || !key.startsWith('asset/') || purge.has(key)) continue;
        if (only && !only.has(key)) continue;
        const data = parse(sh);
        if (!data || upload) continue;
        board.patch(model(), 'asset', key.slice(6), { ...data, trashedAt: data.trashedAt || now() });
        back = true;
      }
      if (back) { cur = records(); draw.add('trash'); }
      const calm = !d.quiet || d.quiet(), ops = [];
      for (const [key, data] of cur) {
        if (only && !only.has(key)) continue;
        const sh = S.shadow[key], json = board.canon(data);
        if (sh && !sh.gone && sh.json === json) continue;
        if (blocked.get(key) === json) continue;
        if (!calm && !only && last.get(key) !== json) continue;
        const [kind, uid] = split(key);
        ops.push({ key, kind, uid, base: upload && !sh ? 0 : sh ? sh.rev : 0, data, json });
      }
      for (const [key, sh] of Object.entries(S.shadow)) {
        if (!sh || sh.gone || cur.has(key) || (only && !only.has(key))) continue;
        const [kind, uid] = split(key);
        if (kind === 'meta' || (kind === 'asset' && !purge.has(key))) continue;
        ops.push({ key, kind, uid, base: sh.rev, gone: true, json: null });
      }
      for (const key of [...purge]) if (!S.shadow[key] && !cur.has(key)) purge.delete(key);
      if (!only) last = new Map([...cur].map(([k, v]) => [k, board.canon(v)]));
      return { ops, cur };
    }
    // Requests in the order the server must see them: meta, new groups (parents first), sounds, references and dynamic
    // sounds, then deletes, which go in the last request.
    function batches(ops) {
      const depth = (op) => { if (op.kind !== 'cat' || !op.data) return 0; let n = 0; const ids = new Map(ops.filter((o) => o.kind === 'cat' && o.data).map((o) => [o.uid, o.data])); for (let p = op.data.parent; p && ids.has(p) && n < 12; p = ids.get(p).parent) n++; return n; };
      const writes = ops.filter((o) => !o.gone).sort((p, q) => ORDER[p.kind] - ORDER[q.kind] || depth(p) - depth(q)), gone = ops.filter((o) => o.gone);
      const out = [];
      let cur = [], bytes = 0;
      for (const op of [...writes, ...gone]) {
        const size = op.json ? board.utf8(op.json) : 64;
        if (cur.length && (cur.length >= OPS_MAX || bytes + size > REQ_BYTES)) { out.push(cur); cur = []; bytes = 0; }
        cur.push(op); bytes += size;
      }
      if (cur.length) out.push(cur);
      return out;
    }

    /* ---------- bytes ---------- */
    const localBytes = async (key) => { try { return await store.bytes(key, { local: true }); } catch { return null; } };
    // The live object a key belongs to: a version, a stem or a project reference.
    function holderOf(key) {
      const m = model();
      for (const a of [...m.assets, ...m.trash]) for (const v of [...(a.versions || []), ...(a.drafts || [])]) {
        if (v.key === key) return v;
        for (const s of v.stems || []) if (s && s.key === key) return s;
      }
      return (m.refs || []).find((r) => r && r.key === key) || null;
    }
    // Every sha the ops point at is on the server before the ops go. Missing shas are worked out from the local bytes
    // and written into the record; what cannot be sent now keeps its record back this round.
    async function bytesFor(ops) {
      let filled = false;
      for (const op of ops) if (op.data) for (const x of board.shasOf(op.kind, op.data)) {
        if (x.sha) continue;
        const u8 = await localBytes(x.key), holder = holderOf(x.key);
        if (!u8 || !holder || !d.sha256) continue;
        holder.sha256 = await d.sha256(u8);
        if (holder.bytes === undefined || holder.bytes === null) holder.bytes = u8.length;
        filled = true;
      }
      if (filled) {
        const cur = records();
        for (const op of ops) if (op.data && cur.has(op.key)) { op.data = cur.get(op.key); op.json = board.canon(op.data); }
      }
      const want = [];
      for (const op of ops) if (op.data) for (const x of board.shasOf(op.kind, op.data)) if (x.sha && !has.has(x.sha)) want.push({ ...x, op });
      if (want.length) {
        const shas = [...new Set(want.map((x) => x.sha))];
        for (let i = 0; i < shas.length; i += SHAS_MAX) {
          const r = await post(`/boards/${S.board}/blobs`, { v: PROTO, shas: shas.slice(i, i + SHAS_MAX) });
          if (r.status !== 200 || !r.data) return ops.filter((op) => !want.some((x) => x.op === op));
          for (const sha of r.data.have || []) has.add(sha);
          for (const [sha, at] of Object.entries(r.data.part || {})) parts.set(sha, +at || 0);
        }
        const todo = want.filter((x) => !has.has(x.sha)).sort((p, q) => p.rank - q.rank);
        sending = { sent: 0, all: new Set(todo.map((x) => x.sha)).size };
        for (const x of todo) {
          if (has.has(x.sha)) continue;
          const how = await sendBlob(x);
          if (how === 'ok') { sending.sent++; continue; }
          if (how === 'refused') blocked.set(x.op.key, x.op.json);
          if (how === 'down') break;
        }
      }
      return ops.filter((op) => !op.data || board.shasOf(op.kind, op.data).every((x) => !x.sha || has.has(x.sha)));
    }
    // 'ok', 'later' (bytes not here), 'refused' (the server will not take them: full, too large, wrong bytes), 'down'.
    async function sendBlob(x) {
      if (x.job) {
        const r = await post(`/boards/${S.board}/blobs/${x.sha}/job`, { v: PROTO, job: x.job, stem: x.stem });
        if (r.status === 200) { has.add(x.sha); return 'ok'; }
        if (r.status !== 404) return r.status === 0 || r.status >= 500 || r.status === 429 ? 'down' : 'refused';
      }
      const u8 = await localBytes(x.key);
      if (!u8) return 'later';
      if (u8.length > BLOB_MAX) { fullOnce(); return 'refused'; }
      let at = parts.get(x.sha) || 0;
      for (let n = 0; n < 10000; n++) {
        const r = await post(`/boards/${S.board}/blobs/${x.sha}?at=${at}&size=${u8.length}`, u8.subarray(at, at + CHUNK_MAX), { raw: true });
        if (r.status === 200 && r.data) {
          if (r.data.done) { has.add(x.sha); parts.delete(x.sha); return 'ok'; }
          at = +r.data.at || 0; parts.set(x.sha, at); continue;
        }
        if (r.status === 409 && r.code === 'offset') { const e = r.data && r.data.error; at = e && typeof e.at === 'number' ? e.at : 0; parts.set(x.sha, at); continue; }
        if ((r.status === 409 && r.code === 'board_full') || r.status === 413) { fullOnce(); return 'refused'; }
        if (r.status === 400) { parts.delete(x.sha); return 'refused'; }
        return 'down';
      }
      return 'down';
    }
    function fullOnce() { if (!toldFull) { toldFull = true; say('syncFull'); } }
    // Sounds the server lost its file of are sent again by a computer that has them, every 30 minutes.
    async function heal() {
      if (now() < healAt) return;
      healAt = now() + HEAL_MS;
      const mine = [];
      for (const [key, sh] of Object.entries(S.shadow)) {
        if (!sh || sh.gone || typeof sh.json !== 'string') continue;
        const [kind] = split(key);
        for (const x of board.shasOf(kind, JSON.parse(sh.json))) if (x.sha && store.saved && store.saved.has(x.key)) mine.push(x);
      }
      const shas = [...new Set(mine.map((x) => x.sha))];
      for (let i = 0; i < shas.length; i += SHAS_MAX) {
        const r = await post(`/boards/${S.board}/blobs`, { v: PROTO, shas: shas.slice(i, i + SHAS_MAX) });
        if (r.status !== 200 || !r.data) return;
        const there = new Set(r.data.have || []);
        for (const x of mine) if (shas.slice(i, i + SHAS_MAX).includes(x.sha) && !there.has(x.sha)) { has.delete(x.sha); if ((await sendBlob({ ...x, job: null })) === 'down') return; }
      }
    }
    // Received sounds: the version in use and the drafts, up to 4 MB, are fetched in the background, two at a time.
    const queue = [];
    let fetchingNow = 0;
    function prefetch(data) {
      for (const x of board.shasOf('asset', data)) if ((x.rank === 0 || x.rank === 1) && x.sha && x.size <= PREFETCH_MAX && !(store.saved && store.saved.has(x.key)) && !queue.includes(x.key)) queue.push(x.key);
      pump();
    }
    function pump() {
      while (fetchingNow < PREFETCH_AT_ONCE && queue.length) {
        const key = queue.shift();
        fetchingNow++;
        Promise.resolve().then(() => store.bytes(key)).catch(() => null).then(() => { fetchingNow--; pump(); });
      }
    }
    // A sound that is not on this computer, from this board's store of bytes. Checked against its sha (twice at most).
    // One the server does not have is left silent for the rest of the visit.
    async function fetchKey(key) {
      if (!S || !S.made) return null;
      const holder = holderOf(key), sha = holder && holder.sha256;
      if (!sha || silent.has(sha)) return null;
      for (let i = 0; i < 2; i++) {
        const r = await call('GET', `/boards/${S.board}/blobs/${sha}`, undefined, { bytes: true });
        if (r.status === 404) { silent.add(sha); return null; }
        if (r.status !== 200 || !r.bytes) return null;
        if (!d.sha256 || (await d.sha256(r.bytes)) === sha) return r.bytes;
      }
      return null;
    }

    /* ---------- sending ---------- */
    // Sends ops (already in order) and takes the answers. claim: the claim of H (a sound being made elsewhere is
    // given back with genTaken). Returns the keys the server now holds as sent.
    async function send(ops, opts) {
      const o = opts || {}, won = new Set();
      for (const chunk of batches(ops)) {
        const r = await post(`/boards/${S.board}/sync`, { v: PROTO, dev: S.dev, since: S.cursor, ops: chunk.map((op) => (op.gone ? { kind: op.kind, uid: op.uid, base: op.base, gone: true } : { kind: op.kind, uid: op.uid, base: op.base, data: op.data })) });
        if (r.status !== 200 || !r.data) return { won, ok: false };
        const results = Array.isArray(r.data.results) ? r.data.results : [], cur = records();
        for (const [i, op] of chunk.entries()) {
          const res = results[i] || {}, sh = S.shadow[op.key];
          if (typeof res.rev === 'number' || typeof res.same === 'number') {
            const rev = typeof res.rev === 'number' ? res.rev : res.same;
            S.shadow[op.key] = { rev, born: (sh && sh.born) || rev, dev: S.dev, at: res.at ?? (sh && sh.at) ?? null, gone: !!op.gone, json: op.gone ? (sh ? sh.json : null) : op.json };
            if (op.gone) purge.delete(op.key);
            blocked.delete(op.key);
            won.add(op.key);
          } else if (res.conflict) conflict(op, res.conflict, cur, o);
          else if (Array.isArray(res.need)) for (const sha of res.need) has.delete(sha);
          else if (res.bad === 'trash_first') { const a = findAsset(op.uid); if (a && cur.has(op.key)) { board.patch(model(), 'asset', op.uid, { ...cur.get(op.key), trashedAt: now() }); purge.delete(op.key); draw.add(a); } else purge.delete(op.key); }
          else if (res.bad === 'versions') mendVersions(op, cur);
          else if (res.bad) { blocked.set(op.key, op.json); if (res.bad === 'board_full') fullOnce(); else lostOnce('syncLost', nameOf(op.data), op.key); }
        }
        touched = true;
        if ((await take(r.data, records())) === 'reset') return { won, ok: false };
      }
      return { won, ok: true };
    }
    function conflict(op, c, cur, o) {
      const key = op.key, sh = S.shadow[key], theirs = c.gone ? null : c.data, own = c.dev === S.dev;
      const mine = cur.has(key) ? cur.get(key) : null;
      if (upload) { S.shadow[key] = { rev: c.rev, born: (sh && sh.born) || c.rev, dev: c.dev, at: c.at ?? null, gone: !!c.gone, json: c.data != null ? board.canon(c.data) : null }; return; }
      let data;
      if (o.claim && theirs && theirs.work && theirs.work.dev && theirs.work.dev !== S.dev) {
        // Another computer is already making this sound: the server's record stands here too.
        data = theirs;
        say('genTaken', nameOf(theirs), key);
      } else {
        const m = board.merge3(op.kind, parse(sh), mine, theirs, own);
        data = m.data;
        if (!own && !o.quiet) { if (m.lost) lostOnce('syncLost', nameOf(mine), key); if (m.gone) say('syncGone', nameOf(mine), key); }
      }
      if (board.canon(data) !== board.canon(mine)) {
        const obj = board.patch(model(), op.kind, op.uid, data);
        if (data) cur.set(key, data); else cur.delete(key);
        draw.add(obj || op.kind);
      }
      S.shadow[key] = { rev: c.rev, born: (sh && sh.born) || c.rev, dev: c.dev, at: c.at ?? null, gone: !!c.gone, json: c.data != null ? board.canon(c.data) : sh ? sh.json : null };
    }
    // The server keeps every version it had: the ones this computer dropped go back in, its other edits stay.
    function mendVersions(op, cur) {
      const sh = parse(S.shadow[op.key]), mine = cur.get(op.key);
      if (!sh || !mine) return;
      const ids = new Set(sh.versions.map((v) => v.id));
      const data = board.sane({ ...mine, versions: [...sh.versions, ...mine.versions.filter((v) => !ids.has(v.id))] });
      const obj = board.patch(model(), 'asset', op.uid, data);
      if (obj) { cur.set(op.key, data); draw.add(obj); }
    }
    async function make() {
      const r = await post('/boards', { v: PROTO, board: S.board, first: !!S.make.first, home: !!S.make.home });
      if (r.status === 200 && r.data) {
        if (r.data.board && r.data.board !== S.board) {
          // The account has a board already: this one is kept apart (sent as a board of its own), the page opens home.
          S.make = { first: false, home: false };
          await save();
          stopped = true; settleReady();
          if (d.moved) d.moved({ board: r.data.board });
          return false;
        }
        S.made = true;
        if (r.data.epoch != null) S.epoch = r.data.epoch;
        await save();
        return true;
      }
      if (r.status === 409 && r.code === 'board_full') { say('boardLimit'); quit('off'); }
      return false;
    }
    async function boardThere() {
      if (!hasBoard) { try { hasBoard = (await store.get('board')) !== undefined; } catch { hasBoard = false; } }
      return hasBoard;
    }

    /* ---------- a round ---------- */
    async function round() {
      if (!eligible()) { settleReady(); return; }
      if (!(await boardThere()) && (!S.made || S.pulled)) { settleReady(); return; } // nothing on disk: nothing goes up
      if (!S.made) {
        if (S.seed && board.pristine(d.snapshot())) { settleReady(); return; } // an untouched board never goes up
        if (!(await make())) return;
      }
      if (!upload && !(await pull())) return;
      if (!(await boardThere())) return;
      await heal();
      const { ops } = dirty(null);
      if (!ops.length) { finished(); return; }
      const ready = await bytesFor(ops);
      if (ready.length) await send(ready, {});
      finished();
    }
    function finished() {
      if (upload && S.made && !outstanding()) { stopped = true; if (doneOk) { doneOk(); doneOk = null; } }
      flushDraw();
    }
    // How many records still differ from the server (the refused ones not counted).
    function outstanding() {
      const cur = records();
      let n = 0;
      for (const [key, data] of cur) { const sh = S.shadow[key], json = board.canon(data); if ((!sh || sh.gone || sh.json !== json) && blocked.get(key) !== json) n++; }
      for (const [key, sh] of Object.entries(S.shadow)) if (sh && !sh.gone && !cur.has(key) && !key.startsWith('meta/') && (!key.startsWith('asset/') || purge.has(key))) n++;
      return n;
    }
    function tick() { return exclusive(() => round().catch(() => { backoff = Math.min(BACK_MAX, backoff ? backoff * 2 : BACK_MIN); })); }
    function pace() {
      if (backoff) return backoff;
      if (d.hidden && d.hidden()) return HIDDEN;
      return now() - activity < ACTIVE ? FAST : SLOW;
    }
    function schedule(ms) {
      if (!started || stopped || off || old) return;
      const at = now() + Math.max(ms, rest - now(), lastReq + GAP - now(), 0);
      if (timer && timerAt <= at) return;
      unlater(timer);
      timerAt = at;
      timer = later(() => { timer = 0; tick().then(() => schedule(pace())); }, at - now());
    }

    /* ---------- the page's side ---------- */
    async function claim(assets) {
      const keys = new Set((assets || []).filter((a) => a && a.key).map((a) => 'asset/' + a.key));
      if (!keys.size) return true;
      if (!S || off || old || stopped || !S.made) return true; // not synced (or not on the server yet): nobody else can be making it
      if (!eligible()) return false;
      return exclusive(async () => {
        for (let n = 0; n < 3; n++) {
          const { ops } = dirty(keys);
          if (!ops.length) return [...keys].every((k) => { const a = findAsset(k.slice(6)); return !a || !a.work || !a.work.dev || a.work.dev === S.dev; });
          const r = await send(ops, { claim: true });
          if (!r.ok) { say('syncOff'); return false; }
          if ([...keys].some((k) => { const a = findAsset(k.slice(6)); return a && a.work && a.work.dev && a.work.dev !== S.dev; })) { await save(); flushDraw(); return false; }
        }
        return false;
      });
    }
    // The records of these sounds go now; the ones the server took are returned (a handover's conditional write).
    async function push(assets) {
      const keys = new Set((assets || []).filter((a) => a && a.key).map((a) => 'asset/' + a.key));
      if (!keys.size || !eligible() || !S.made) return [];
      return exclusive(async () => {
        const { ops } = dirty(keys);
        const { won } = await send(ops, { quiet: true });
        flushDraw();
        return (assets || []).filter((a) => won.has('asset/' + a.key) && a.work && a.work.dev === S.dev);
      });
    }
    // Before the page goes to another board: everything (but what the server refused for good) is sent first.
    async function flush(ms = 5000) {
      if (!S || off || old) return { ok: true, reason: '' };
      if (S.seed && !S.made && board.pristine(d.snapshot())) return { ok: true, reason: '' };
      const end = now() + ms;
      for (;;) {
        await tick();
        if (!outstanding()) return { ok: true, reason: '' };
        if (now() >= end || !eligible() || failSince) return { ok: false, reason: failSince || !eligible() ? 'syncOff' : 'syncBusy' };
        await new Promise((ok) => later(ok, Math.min(GAP, Math.max(0, end - now()))));
      }
    }
    function status() {
      if (!S) return { state: 'off', changes: 0, sounds: [0, 0], blocked: 0 };
      const changes = outstanding() + blocked.size;
      const state = off || old ? 'off' : failSince ? 'offline' : changes ? 'sending' : 'synced';
      return { state, changes, sounds: [sending.sent, sending.all], blocked: blocked.size };
    }

    return {
      start() { if (started || !S) return; started = true; schedule(0); },
      stop() { stopped = true; unlater(timer); timer = 0; unlater(drawTimer); drawTimer = 0; settleReady(); },
      tick, flush, status, claim, push,
      nudge() { activity = now(); schedule(GATHER); },
      wake() { backoff = 0; schedule(0); },
      purge(keys) { for (const k of keys || []) purge.add(String(k).startsWith('asset/') ? String(k) : 'asset/' + k); },
      fetch: fetchKey,
      extra: () => (S ? { sync: { ...S, purge: [...purge] } } : {}),
      ready: () => readyP,
      done: () => doneP,
      peers: () => ({ up: server.up + (now() - server.at) / 1000, now: server.now + (now() - server.at) / 1000, peers: server.peers.map((p) => ({ dev: p.dev, age: p.age + (now() - server.at) / 1000 })),
        at: (a) => { const sh = S && a && S.shadow['asset/' + a.key]; return sh && typeof sh.at === 'number' ? sh.at : null; } }),
      // A board that is on the server and was never received here takes no input (a board made here has nothing to wait for).
      get pending() { return !!S && !!S.made && !S.pulled && !upload; },
      get record() { return S; },
      get state() { return off ? 'off' : old ? 'old' : stopped ? 'stopped' : started ? 'running' : 'idle'; },
    };
  }

  return { create, record, dbName, newBoard, newDev, scan, list, open, pointer, PROTO, OPS_MAX, CHUNK_MAX, BLOB_MAX };
});
