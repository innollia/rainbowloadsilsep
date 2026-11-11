// The asset board's storage: version records, the split writes (the board record first, then one Blob at a time),
// the three-way restore, the lock that keeps a second tab view-only, and turning stored bytes back into sound.
// IndexedDB, the clock and the Web Locks manager are handed in, so Node runs this file in tests.
//
// assetStore.create(deps) -> one board's store. deps (all optional but the first three for a page that saves):
//   indexedDB, locks (navigator.locks), now, random, setTimeout, clearTimeout,
//   snapshot() -> the v2 record to write, apply(data, buffers, info) -> put a read record on screen (throwing = failed),
//   keys() -> Map(key -> null | () => Blob) of every audio key the board uses now, assets() -> the live asset list,
//   notify(what, n) for 'saveFull' and 'pruned', onLock(result) when a waiting tab takes the board over,
//   synth, measure (assetMeasure), decode(bytes) for sound that is not WAV, sha256(bytes).
// The store it returns:
//   lock() -> true when this tab has the board, restore() -> 'empty' | 'restored' | 'failed',
//   save() (the board record, then every sound not on disk yet, then the clean-up), saveBoard() and saveBlob(key, blob)
//   -> true or false, hold(key, blob) for a sound to write with the next save, put / get / del(key) for small things in
//   the board store, clear() (the user's own "start again": it also works after a read that failed, never in a
//   view-only tab), guard(target, { allow, blocked }), bytes(key), ensureSound(version) (a legacy version is rendered
//   from its asset: ensureSound(version, asset)), importVersion(bytes, { note, sources }), filled(asset, version),
//   newId(), saved (the Set of keys on disk), and the flags locked, ready, readOnly, paused, blobFull, writable, restored.
// blobFull is up while a sound that did not fit is still waiting to be written. It comes down when that sound is
// written, or when the board no longer uses it.
(function (factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  const root = typeof window !== 'undefined' ? window : typeof self !== 'undefined' ? self : null;
  if (root) root.assetStore = api;
})(function () {
  'use strict';

  const DB = 'olmuse-asset-board', LOCK = 'olmuse-asset-board', SNAPSHOT = 2, PEAKS = 200, OPEN_MS = 3000;
  const root = typeof globalThis !== 'undefined' ? globalThis : typeof window !== 'undefined' ? window : {};
  // What a sound from the room's own synth names as its source. The project has not stated a licence or a holder for
  // the synth, so both stay empty here: this is the one place to fill them in.
  const SYNTH = Object.freeze({ name: 'olmuse built-in synth', license: '', holder: '', use: 'Built-in synthesizer' });

  /* ---------- version records ---------- */
  let serial = 0;
  const newId = (now = Date.now(), random = Math.random()) => `v${Math.floor(now).toString(36)}${(serial++ % 1296).toString(36).padStart(2, '0')}${random.toString(36).slice(2, 8)}`;
  const isLegacy = (v) => !v || !v.engine || v.engine === 'legacy';
  // A brought-in sound's sources are what the user recorded for it. Nothing recorded yet is an empty list.
  const importSources = (a) => (a && a.license ? [{ name: a.file || a.id || '', license: a.license, holder: a.holder || '', use: 'Imported sound' }] : []);
  const sourcesFor = (a) => (a && a.imported ? importSources(a) : [{ ...SYNTH }]);
  // Every audio key one version needs: its master and its stems.
  const versionKeys = (v) => (v && v.key ? [v.key, ...(v.stems || []).map((s) => s.key)] : []);

  // A board saved before version records (no v, or v 1) held versions as { change, note, at }. Each becomes a legacy
  // record with an id and its sources. Returns a new record; throws for anything that is not a board this page can read.
  function upgradeSnapshot(data, opts) {
    if (!data || typeof data !== 'object' || !Array.isArray(data.assets)) throw new Error('not a saved board');
    const v = data.v ?? 1;
    if (typeof v !== 'number' || v > SNAPSHOT) throw new Error(`saved board is version ${v}; this page reads up to ${SNAPSHOT}`);
    if (v >= SNAPSHOT) return data;
    const id = (opts && opts.id) || (() => newId());
    const up = (a) => {
      if (!a || typeof a !== 'object') throw new Error('saved board holds an asset that is not a record');
      const one = (x) => {
        if (!x || typeof x !== 'object') throw new Error('saved board holds a version that is not a record');
        return { ...x, id: x.id || id(), engine: 'legacy', sources: sourcesFor(a) };
      };
      return { ...a, versions: (Array.isArray(a.versions) ? a.versions : []).map(one), drafts: (Array.isArray(a.drafts) ? a.drafts : []).map(one) };
    };
    return { ...data, v: SNAPSHOT, assets: data.assets.map(up), trash: (Array.isArray(data.trash) ? data.trash : []).map(up) };
  }

  // What the snapshot keeps of a version. A legacy one is its recipe and is rendered again when it is heard. The others
  // keep everything but the decoded sound, which comes back from the ver: Blob.
  function record(v) {
    if (isLegacy(v)) return { id: v.id, at: v.at, note: v.note, change: v.change, engine: 'legacy', sources: v.sources || [] };
    const { sound, ...rest } = v;
    return rest;
  }

  /* ---------- sound in memory: { rate, channels, seconds, chans, mix, stems: [{ name, chans, data }] } ---------- */
  const frames = (chans) => (chans.length ? Math.min(...chans.map((c) => c.length)) : 0);
  // mix and data are the channels averaged into one, so code written for mono keeps working.
  function mono(chans) {
    if (chans.length === 1) return chans[0];
    const n = frames(chans), mix = new Float32Array(n);
    for (const c of chans) for (let i = 0; i < n; i++) mix[i] += c[i] / chans.length;
    return mix;
  }
  // The synth's { rate, seconds, stems: [{ name, data }], mix } in that shape: one channel at the synth's rate.
  const shape = (s) => (s.chans ? s : { rate: s.rate, channels: 1, seconds: s.seconds, chans: [s.mix], mix: s.mix, stems: s.stems.map((x) => ({ name: x.name, chans: [x.data], data: x.data })) });
  // A decoded master and its stems. With no stems the master stands in as the one stem.
  function soundOf(main, stems) {
    const n = frames(main.chans), chans = main.chans.map((c) => (c.length === n ? c : c.subarray(0, n))), mix = mono(chans);
    return { rate: main.rate, channels: chans.length, seconds: n / main.rate, chans, mix, stems: stems && stems.length ? stems : [{ name: 'main', chans, data: mix }] };
  }
  // The outline a tile draws: the loudest sample of any channel in each of `count` slices, as plain numbers.
  function peaksOf(chans, count = PEAKS) {
    const n = frames(chans), size = Math.max(1, Math.floor(n / count)), out = new Array(count).fill(0);
    for (let i = 0; i < count; i++) {
      let top = 0;
      for (const c of chans) for (let j = i * size, stop = Math.min(n, j + size); j < stop; j++) { const a = Math.abs(c[j]); if (a > top) top = a; }
      out[i] = Math.round(top * 1e4) / 1e4;
    }
    return out;
  }
  // A legacy version is rendered by the synth the first time it is heard. nkido and import versions are never rendered
  // here: their stored peaks and measure stay as they are, and v.sound may still be missing (ensureSound brings it).
  function filled(a, v, synth) {
    if (!v || !isLegacy(v) || v.sound) return v;
    const sound = shape(synth.render(a, v.change));
    v.sound = sound; v.peaks = synth.peaks(sound.mix, PEAKS); v.measure = synth.measure(sound);
    return v;
  }

  /* ---------- making room, and versions whose sound is gone ---------- */
  // Oldest legacy versions that are not the one in use go first. nkido and import versions are never removed for space.
  function prune(assets) {
    const old = assets.flatMap((a) => a.versions.map((v) => ({ a, v })).filter((x) => isLegacy(x.v) && x.v !== x.a.versions[x.a.current])).sort((x, y) => x.v.at - y.v.at);
    const cut = old.slice(0, Math.max(1, Math.ceil(old.length / 2)));
    for (const { a, v } of cut) { const now = a.versions[a.current]; a.versions.splice(a.versions.indexOf(v), 1); a.current = a.versions.indexOf(now); }
    return old.length ? cut.length : 0;
  }
  // keys: what the audio store holds. A version whose sound is not all there is dealt with alone: one that a job record
  // (a.work) still names is fetched again, so its job goes back to not got; any other is taken out. The asset's other
  // versions and Blobs are left as they are. Its status moves only where it has to: an approval belongs to the version
  // that was approved, so with that version gone the sound is a draft again; a sound with nothing left is pending;
  // a review with no draft left is over. A sound being made keeps working, and what it goes back to (work.before)
  // moves the same way. Returns { dropped, refetch }, each a list of { asset, id }.
  function mend(data, keys) {
    const out = { dropped: [], refetch: [] };
    for (const a of [...data.assets, ...(data.trash || [])]) {
      const versions = Array.isArray(a.versions) ? a.versions : [], drafts = Array.isArray(a.drafts) ? a.drafts : [];
      const noSource = !!a.hasSource && !keys.has(a.key);
      const lost = (v) => (isLegacy(v) ? noSource : versionKeys(v).some((k) => !keys.has(k)));
      const gone = new Set([...versions, ...drafts].filter(lost));
      if (noSource) a.hasSource = false;
      if (!gone.size) continue;
      const jobs = a.work && Array.isArray(a.work.jobs) ? a.work.jobs : [];
      for (const v of gone) {
        const job = jobs.find((j) => j && j.id === v.id);
        if (job) { job.got = false; out.refetch.push({ asset: a.id, id: v.id }); } else out.dropped.push({ asset: a.id, id: v.id });
      }
      const current = versions[a.current], picked = drafts[a.pick];
      a.versions = versions.filter((v) => !gone.has(v)); a.drafts = drafts.filter((v) => !gone.has(v));
      // The version in use went: the newest one left takes its place.
      a.current = a.versions.includes(current) ? a.versions.indexOf(current) : a.versions.reduce((best, v, i) => (+v.at >= +a.versions[best].at ? i : best), 0);
      a.pick = a.drafts.includes(picked) ? a.drafts.indexOf(picked) : a.drafts.length && a.pick >= 0 ? 0 : -1;
      const making = !!a.work && a.status === 'working';
      if (current && !a.versions.includes(current)) {
        if (a.status === 'approved') a.status = 'draft';
        if (making && a.work.before === 'approved') a.work.before = 'draft';
      }
      if (a.status === 'review' && !a.drafts.length) { a.status = a.versions.length ? 'draft' : 'pending'; a.pick = -1; }
      if (!a.versions.length && !a.drafts.length) { if (making) a.work.before = 'pending'; else a.status = 'pending'; }
    }
    return out;
  }

  /* ---------- bytes ---------- */
  const isWav = (u8) => u8.length >= 12 && u8[0] === 0x52 && u8[1] === 0x49 && u8[2] === 0x46 && u8[3] === 0x46 && u8[8] === 0x57 && u8[9] === 0x41 && u8[10] === 0x56 && u8[11] === 0x45;
  // Anything that is not a WAV goes through the browser's decoder, which hands it back at 48 kHz.
  async function browserDecode(bytes) {
    const Ctx = root.OfflineAudioContext || root.webkitOfflineAudioContext;
    if (!Ctx) throw new Error('this browser cannot decode sound');
    const buf = await new Ctx(2, 1, 48000).decodeAudioData(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength));
    return { rate: buf.sampleRate, bits: null, chans: Array.from({ length: buf.numberOfChannels }, (_, c) => buf.getChannelData(c)) };
  }
  async function sha256(bytes) {
    const subtle = root.crypto && root.crypto.subtle;
    if (!subtle) return null;
    return [...new Uint8Array(await subtle.digest('SHA-256', bytes))].map((b) => b.toString(16).padStart(2, '0')).join('');
  }

  /* ---------- IndexedDB ---------- */
  // A transaction is over when it completes or aborts. A failed request is seen first (its error bubbles up before the
  // abort), so that error is kept for the abort to report and a full disk stays recognisable.
  const done = (q) => new Promise((ok, no) => {
    let seen = null;
    q.onerror = (e) => { seen = (e && e.target && e.target.error) || q.error || seen; };
    q.onabort = () => no(q.error || seen || new Error('transaction aborted'));
    q.oncomplete = () => ok();
  });
  const asked = (r) => new Promise((ok, no) => { r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error || new Error('read failed')); });
  const isFull = (e) => !!e && (e.name === 'QuotaExceededError' || /quota/i.test(e.message || ''));

  /* ---------- the guard of a view-only tab ---------- */
  // While opts.open() is false, clicks, keys, drops and submits stop here, in the capture phase, before any handler of
  // the page sees them. opts.allow is a selector for what stays usable (playing, export, going back, the menu button).
  // Tab and Escape pass. A key with Ctrl, Alt or Meta held is left to the browser (reload, copy, zoom): it is not
  // cancelled, but no handler of the page hears it. opts.blocked(event) hears each cancelled event, for the toast.
  // A store's own guard(target, opts) opens when that tab has the board and has read it back.
  function guard(target, opts) {
    const o = opts || {}, allow = o.allow || '', open = o.open || (() => false);
    const PASS = ['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock', 'F5', 'F11', 'F12'];
    const hush = (e) => { if (e.stopImmediatePropagation) e.stopImmediatePropagation(); else if (e.stopPropagation) e.stopPropagation(); };
    const handler = (e) => {
      if (open()) return;
      const el = e.target;
      if (allow && el && typeof el.closest === 'function' && el.closest(allow)) return;
      if (e.type === 'keydown') {
        if (PASS.includes(e.key)) return;
        if (e.ctrlKey || e.metaKey || e.altKey) { hush(e); return; }
      }
      if (e.preventDefault) e.preventDefault();
      hush(e);
      if (o.blocked) o.blocked(e);
    };
    for (const type of ['click', 'keydown', 'drop', 'submit']) target.addEventListener(type, handler, true);
    return handler;
  }

  function create(deps) {
    const d = deps || {};
    const locks = d.locks, notify = d.notify || (() => {});
    const now = d.now || (() => Date.now()), random = d.random || Math.random;
    const later = d.setTimeout || ((fn, ms) => setTimeout(fn, ms)), cancel = d.clearTimeout || ((t) => clearTimeout(t));
    const measurer = () => d.measure || root.assetMeasure, synthOf = () => d.synth || root.synth;
    const decodeOther = d.decode || browserDecode, digest = d.sha256 || sha256;
    // saved: keys the audio store holds. known: keys the board has used at some point (or that were there at restore),
    // the only ones a clean-up may delete. held: Blobs still to be written, which also play from here until they are.
    // stuck: keys whose Blob did not fit and is still waiting to be written. blobFull is "something is stuck".
    const saved = new Set(), known = new Set(), held = new Map(), stuck = new Set(), decoding = new WeakMap();
    const state = { answered: false, locked: false, ready: false, paused: false, closed: false, restored: null };
    // told: whether the full-disk toast is out for the board record and for the sounds. Each has its own spell (the
    // board record until it is written again, the sounds until none is stuck); the toast is said when one starts
    // while the other is not running.
    const told = { board: false, blob: false };
    // upgrading: the record on disk is still from before version records, so the next board write keeps a copy of it.
    let dbOpen = null, upgrading = false, lastError = null, cycle = null, lockAsked = null;
    let queue = Promise.resolve(), restoring = Promise.resolve();

    const idb = () => (dbOpen ||= new Promise((ok, no) => {
      const r = d.indexedDB.open(DB, 1);
      r.onupgradeneeded = () => { r.result.createObjectStore('board'); r.result.createObjectStore('audio'); };
      r.onsuccess = () => ok(r.result); r.onerror = () => no(r.error || new Error('open failed')); r.onblocked = () => no(new Error('blocked'));
    }).catch((e) => { dbOpen = null; throw e; }));
    // The database, or an error when it has not opened within three seconds.
    function opened() {
      let timer = 0;
      const slow = new Promise((_, no) => { timer = later(() => no(new Error('the saved board took too long to open')), OPEN_MS); });
      return Promise.race([idb(), slow]).finally(() => cancel(timer));
    }
    // This tab may write: it holds the board, has read it back since, and that read did not fail.
    const writable = () => state.locked && state.ready && !state.paused && !state.closed;
    // Writes run one after another, so an older snapshot never lands after a newer one.
    const enqueue = (fn) => { const p = queue.then(fn); queue = p.catch(() => {}); return p; };
    function tellFull(what) { const quiet = !told.board && !told.blob; told[what] = true; if (quiet) notify('saveFull'); }
    // That key no longer waits for room: its sound was written, or the board stopped using it.
    function unstick(key) { stuck.delete(key); if (!stuck.size) told.blob = false; }

    /* ---------- writes ---------- */
    // One snapshot in a transaction that opens the board store only. True when it is on disk.
    async function writeBoard() {
      if (!writable()) return false;
      try {
        const data = d.snapshot();
        const q = (await idb()).transaction('board', 'readwrite'), s = q.objectStore('board');
        if (upgrading) {
          // The first v2 write keeps the record it replaces: read and copied to board.v1 in this same transaction, where
          // it stays until a later visit has read v2 back.
          const r = s.get('board');
          r.onsuccess = () => { const was = r.result; if (was && typeof was === 'object' && (was.v ?? 1) < SNAPSHOT) s.put(was, 'board.v1'); s.put(data, 'board'); };
        } else s.put(data, 'board');
        await done(q);
        upgrading = false; lastError = null; told.board = false;
        return true;
      } catch (e) { lastError = e || new Error('write failed'); return false; }
    }
    // One Blob, one transaction: 'ok', 'full' (no room for it) or 'failed'. Only a key whose write finished counts as
    // saved. One that did not fit is stuck, which is what blobFull tells, and the full-disk toast is said for it once.
    async function writeBlob(key, blob) {
      if (!writable()) return 'failed';
      try {
        const q = (await idb()).transaction('audio', 'readwrite');
        q.objectStore('audio').put(blob, key);
        await done(q);
      } catch (e) {
        if (!isFull(e)) return 'failed';
        stuck.add(key); tellFull('blob');
        return 'full';
      }
      saved.add(key); held.delete(key); unstick(key);
      return 'ok';
    }
    // Keys nothing uses any more, in a transaction of their own, and only after a board write succeeded.
    async function dropUnused() {
      if (!writable() || !d.keys) return;
      const want = d.keys(), gone = [...saved].filter((k) => known.has(k) && !want.has(k));
      for (const k of [...held.keys()]) if (known.has(k) && !want.has(k)) held.delete(k);
      if (!gone.length) return;
      try {
        const q = (await idb()).transaction('audio', 'readwrite'), s = q.objectStore('audio');
        for (const k of gone) s.delete(k);
        await done(q);
        for (const k of gone) { saved.delete(k); known.delete(k); }
      } catch { /* they stay for the next round */ }
    }
    // A whole save: the board record, then every Blob not on disk yet, then the clean-up.
    async function runCycle() {
      if (!writable()) return false;
      let ok = await writeBoard();
      if (!ok && isFull(lastError)) {
        // The board record itself did not fit: old legacy versions go until it does.
        const list = d.assets ? d.assets() : [];
        let cleared = 0;
        while (!ok && isFull(lastError)) {
          const n = prune(list);
          if (!n) break;
          cleared += n; ok = await writeBoard();
        }
        if (ok) notify('pruned', cleared); else if (isFull(lastError)) tellFull('board');
      }
      const want = d.keys ? d.keys() : new Map();
      for (const key of want.keys()) known.add(key);
      // A sound that does not fit must not keep the ones after it off the disk: it is passed over, and so is anything
      // at least as big in this round. The smaller ones are still written. All of them are tried again next round.
      let tight = Infinity;
      for (const [key, make] of want) {
        if (saved.has(key)) continue;
        const blob = held.get(key) || (make ? make() : null);
        if (!blob) continue;
        if (blob.size >= tight) { stuck.add(key); continue; }
        if ((await writeBlob(key, blob)) === 'full') tight = blob.size;
      }
      // A sound that did not fit and has since left the board is not waited for any longer.
      for (const key of [...stuck]) if (known.has(key) && !want.has(key)) unstick(key);
      if (ok) await dropUnused();
      return ok;
    }
    // Asked for many times in a row, it runs once more with the newest state.
    function save() {
      if (!writable()) return Promise.resolve(false);
      if (!cycle) cycle = enqueue(() => { cycle = null; return runCycle(); });
      return cycle;
    }
    // The board record alone, for a caller that cannot wait for the sounds (a request about to be sent). A record on
    // disk that names a sound whose bytes are not there yet comes back with that sound gone, so when a sound is still
    // owed its write a whole save follows right behind instead of waiting for the page's next one.
    function owed() {
      if (!d.keys) return false;
      for (const [key, make] of d.keys()) if (!saved.has(key) && !stuck.has(key) && (held.has(key) || make)) return true;
      return false;
    }
    const saveBoard = () => { const wrote = enqueue(writeBoard); if (writable() && owed()) save(); return wrote; };
    // A Blob there was no room for stays in memory: it plays from there, and every save tries it again for as long as
    // the board uses its key.
    const saveBlob = (key, blob) => enqueue(async () => {
      const how = await writeBlob(key, blob);
      if (how === 'full') held.set(key, blob);
      return how === 'ok';
    });
    function hold(key, blob) { held.set(key, blob); }

    // Small things beside the board record in the board store (the linked game folder, a request body).
    const put = (key, value) => enqueue(async () => {
      if (!writable()) return false;
      try { const q = (await idb()).transaction('board', 'readwrite'); q.objectStore('board').put(value, key); await done(q); return true; } catch { return false; }
    });
    const del = (key) => enqueue(async () => {
      if (!writable()) return false;
      try { const q = (await idb()).transaction('board', 'readwrite'); q.objectStore('board').delete(key); await done(q); return true; } catch { return false; }
    });
    async function get(key) {
      try { return await asked((await idb()).transaction('board').objectStore('board').get(key)); } catch { return undefined; }
    }
    // "Start again": both stores emptied. Nothing is written after it; the page reloads. This is the user's own reset,
    // not a save, so it also works on a visit whose saved board could not be read: a record that will never open
    // would otherwise stay in the way for good. A view-only tab leaves the board to the tab that has it. If the
    // emptying fails, the store goes on as it was.
    function clear() {
      if (!state.locked || !state.ready || state.closed) return Promise.resolve(false);
      state.closed = true;
      return enqueue(async () => {
        try {
          const q = (await opened()).transaction(['board', 'audio'], 'readwrite');
          q.objectStore('board').clear(); q.objectStore('audio').clear();
          await done(q);
        } catch { state.closed = false; return false; }
        saved.clear(); known.clear(); held.clear(); stuck.clear(); told.board = told.blob = false; upgrading = false;
        return true;
      });
    }

    /* ---------- restore: 'empty', 'restored' or 'failed' ---------- */
    async function read() {
      const db = await opened();
      const q = db.transaction(['board', 'audio']), board = q.objectStore('board');
      const [raw, old, dir, keys] = await Promise.all([asked(board.get('board')), asked(board.getKey('board.v1')), asked(board.get('gameDir')), asked(q.objectStore('audio').getAllKeys())]);
      const stored = new Set(keys.map(String));
      const took = () => { saved.clear(); known.clear(); held.clear(); stuck.clear(); told.blob = false; for (const k of stored) { saved.add(k); known.add(k); } };
      if (raw == null) { took(); upgrading = false; return 'empty'; }
      const data = upgradeSnapshot(raw), present = new Set(stored);
      // Read now: reference files, and the Float32 sources legacy versions are rendered from. ver: Blobs wait until heard.
      const need = [...stored].filter((k) => k.startsWith('ref:'));
      for (const a of [...data.assets, ...(data.trash || [])]) if (a.hasSource && stored.has(a.key) && !need.includes(a.key)) need.push(a.key);
      const buffers = new Map();
      if (need.length) {
        const audio = db.transaction('audio').objectStore('audio');
        const blobs = await Promise.all(need.map((k) => asked(audio.get(k))));
        for (const [i, k] of need.entries()) {
          const ref = k.startsWith('ref:');
          try {
            const buf = await blobs[i].arrayBuffer();
            if (ref || buf.byteLength % 4 === 0) buffers.set(k, buf); else present.delete(k);
          } catch { if (!ref) present.delete(k); } // unreadable: as if it were not there
        }
      }
      const fixed = mend(data, present);
      d.apply(data, buffers, { gameDir: dir || null, dropped: fixed.dropped, refetch: fixed.refetch });
      took();
      upgrading = (raw.v ?? 1) < SNAPSHOT;
      // The copy of the old record has done its job once a v2 record has been read back.
      if (!upgrading && old !== undefined && state.locked && !state.paused && !state.closed) {
        try { const q3 = db.transaction('board', 'readwrite'); q3.objectStore('board').delete('board.v1'); await done(q3); } catch { /* next visit */ }
      }
      return 'restored';
    }
    async function readBack() {
      const mine = state.locked;
      let result = 'failed';
      try { result = await read(); } catch { result = 'failed'; }
      // A board that could not be read is never written over: nothing is saved or deleted for the rest of the visit.
      if (result === 'failed') state.paused = true;
      state.restored = result; state.ready = mine && state.locked;
      return result;
    }
    function restore() { const p = restoring.then(readBack); restoring = p.catch(() => {}); return p; }

    /* ---------- one tab at a time ---------- */
    // Resolves true when this tab has the board. False means another tab has it: this one stays view-only and waits in
    // line, and when its turn comes the board is read again before anything is accepted (deps.onLock hears the result).
    function lock() {
      if (lockAsked) return lockAsked;
      const kept = () => new Promise(() => {}); // held for as long as the tab lives
      const answer = (ok, got) => { state.locked = got; state.answered = true; ok(got); };
      lockAsked = new Promise((ok) => {
        if (!locks || typeof locks.request !== 'function') { answer(ok, true); return; }
        let asking;
        try {
          asking = locks.request(LOCK, { ifAvailable: true }, (got) => {
            if (got) { answer(ok, true); return kept(); }
            answer(ok, false);
            Promise.resolve().then(() => locks.request(LOCK, () => { takeOver(); return kept(); })).catch(() => {});
            return undefined;
          });
        } catch (e) { asking = Promise.reject(e); }
        // A browser that refuses locks here (an opaque origin) is treated as the only tab.
        Promise.resolve(asking).catch(() => { if (!state.answered) answer(ok, true); });
      });
      return lockAsked;
    }
    function takeOver() {
      state.locked = true; state.ready = false;
      restore().then((result) => { if (d.onLock) d.onLock(result); }).catch(() => {});
    }
    // Input is taken once this tab has the board and has read it back.
    const guardHere = (target, opts) => guard(target, { ...(opts || {}), open: () => state.ready });

    /* ---------- sound ---------- */
    async function bytes(key) {
      let blob = held.get(key);
      if (!blob) blob = await asked((await idb()).transaction('audio').objectStore('audio').get(key));
      if (!blob) throw new Error(`sound ${key} is not stored`);
      return new Uint8Array(await blob.arrayBuffer());
    }
    // A WAV is read sample for sample; anything else, and a WAV this reader does not take, goes to the decoder.
    async function decodeBytes(u8) {
      if (isWav(u8)) { try { return measurer().readWav(u8); } catch { /* let the decoder try */ } }
      return decodeOther(u8);
    }
    async function unpack(v) {
      const main = await decodeBytes(await bytes(v.key)), stems = [], names = new Set();
      for (const [i, s] of (v.stems || []).entries()) {
        const one = await decodeBytes(await bytes(s.key)), label = String(s.label || `stem ${i + 1}`);
        let name = label;
        for (let k = 2; names.has(name); k++) name = `${label} ${k}`;
        names.add(name); stems.push({ name, chans: one.chans, data: mono(one.chans) });
      }
      return soundOf(main, stems);
    }
    // The sound of a version, decoded once. A legacy version has no stored sound: it is rendered from its asset, which
    // has to come with it.
    function ensureSound(v, a) {
      if (!v) return Promise.reject(new Error('no version'));
      if (v.sound) return Promise.resolve(v.sound);
      if (isLegacy(v)) {
        if (!a) return Promise.reject(new Error('a legacy version is rendered from its asset: ensureSound(version, asset)'));
        try { return Promise.resolve(filled(a, v, synthOf()).sound); } catch (e) { return Promise.reject(e); }
      }
      let p = decoding.get(v);
      if (!p) {
        p = unpack(v).then((sound) => { v.sound = sound; return sound; }).finally(() => decoding.delete(v));
        decoding.set(v, p);
      }
      return p;
    }
    // A file the user brought in becomes a version that keeps the file's own bytes. They wait in `held` for the next save.
    async function importVersion(u8, extra) {
      const x = extra || {}, sound = await decodeBytes(u8);
      if (!frames(sound.chans)) throw new Error('empty sound');
      const m = measurer().measure(sound), id = x.id || newId(now(), random());
      const v = {
        id, at: now(), note: x.note ?? null, engine: 'import', job: null, parent: null, draft: null,
        source: null, seconds: m.seconds, bpm: null, prompt: null, model: null, sources: x.sources || [],
        measure: m, issues: [], peaks: peaksOf(sound.chans), key: `ver:${id}`, stems: [],
        rate: sound.rate, channels: sound.chans.length, bits: sound.bits ?? null, bytes: u8.length, sha256: await digest(u8),
      };
      held.set(v.key, new Blob([u8]));
      return v;
    }

    return {
      lock, restore, save, saveBoard, saveBlob, hold, put, get, del, clear, guard: guardHere, bytes, ensureSound, importVersion,
      filled: (a, v) => filled(a, v, synthOf()), newId: () => newId(now(), random()), saved,
      get locked() { return state.locked; }, get ready() { return state.ready; }, get paused() { return state.paused; },
      get blobFull() { return stuck.size > 0; }, get writable() { return writable(); }, get restored() { return state.restored; },
      // Another tab has the board, so this one only shows it.
      get readOnly() { return state.answered && !state.locked; },
    };
  }

  return { create, upgradeSnapshot, guard, record, filled, shape, soundOf, mono, peaksOf, prune, mend, versionKeys, importSources, sourcesFor, newId, isLegacy, SYNTH, SNAPSHOT };
});
